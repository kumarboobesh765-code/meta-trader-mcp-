#!/usr/bin/env python3
"""Guarded Freebuff entry point for the MetaTrader MCP server.

Safety rails (see README.md at the project root):
  1. NEVER opens the MetaTrader 5 terminal. If MT5 is not already running it
     stops and asks the human to open MT5 manually before retrying.
  2. Refuses to connect to a LIVE (real-money) account unless the human has
     explicitly set MT5_ALLOW_LIVE=1 in .env. Demo/contest accounts only.
  3. Reads credentials only from .env - never from argv or .agents/mcp.json -
     so secrets stay out of git, shell history, and process listings.
  4. Always runs the MCP server over stdio; it never binds a network port.

All diagnostics go to stderr; stdout is reserved for the MCP stdio protocol.

Usage:
    python mt5_mcp_guarded.py [--check-only] [extra server args]

    --check-only   Run the safety pre-flight (MT5 running? account is demo?)
                   and exit without starting the MCP server.
"""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

TRADE_MODE_NAMES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


def log(msg: str) -> None:
    print(f"[mt5-guard] {msg}", file=sys.stderr, flush=True)


def fail(msg: str) -> None:
    log(msg)
    sys.exit(1)


def load_env_file(path: str) -> dict:
    """Minimal .env parser (KEY=VALUE lines, # comments, optional quotes)."""
    values = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_credentials(env: dict):
    """Accept both the documented UPPER case names and the server's lowercase ones."""
    login = env.get("login") or env.get("LOGIN") or ""
    password = env.get("password") or env.get("PASSWORD") or ""
    server = env.get("server") or env.get("SERVER") or ""
    return login, password, server


def terminal_process_names():
    names = {"terminal64.exe", "terminal.exe"}
    custom = os.environ.get("MT5_PATH")
    if custom:
        names.add(os.path.basename(custom))
    return sorted(names)


def mt5_terminal_is_running() -> bool:
    """True iff an MT5 terminal process is already open (we NEVER start one)."""
    for name in terminal_process_names():
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            fail(
                "Failing closed: could not run 'tasklist' to check whether MT5 is "
                f"already running ({exc}). This launcher never opens MT5 itself."
            )
        if name.lower() in out.stdout.lower():
            return True
    return False


def warn_if_env_is_tracked() -> None:
    """Credential-leak guard: .env must never be committed to git."""
    try:
        tracked = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "ls-files", "--", ".env"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if tracked.stdout.strip():
        fail(
            "CREDENTIAL LEAK: .env is tracked by git. Remove it first "
            "(git rm --cached .env) before doing anything else."
        )
    try:
        ignored = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "check-ignore", "-q", ".env"],
            capture_output=True,
            timeout=20,
        )
        if ignored.returncode == 1:
            log("WARNING: .env is not git-ignored - add it to .gitignore now.")
    except (OSError, subprocess.SubprocessError):
        pass


def preflight(login: str, password: str, server: str) -> None:
    # Guard 1: MT5 must already be open. Never auto-launch the terminal.
    if not mt5_terminal_is_running():
        fail(
            "MetaTrader 5 is NOT running. This launcher never opens MT5 "
            "automatically - please open MetaTrader 5 manually, log in to your "
            "DEMO account, and then retry."
        )

    import MetaTrader5 as mt5  # Windows-only, imported lazily

    try:
        login_number = int(login)
    except ValueError:
        fail(f"Invalid 'login' in .env: expected a number, got {login!r}.")

    if not mt5.initialize(login=login_number, password=password, server=server):
        error_code, error_message = mt5.last_error()
        fail(
            f"Could not connect to MT5 (error {error_code}: {error_message}). "
            "Check the login/password/server values in .env. Nothing was traded "
            "and no account was changed by this check."
        )

    try:
        account = mt5.account_info()
        if account is None:
            fail("Connected to MT5 but could not read account info.")

        # Guard 2: real-money accounts require an explicit human opt-in.
        if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL and os.environ.get("MT5_ALLOW_LIVE", "0") != "1":
            fail(
                f"REFUSING TO START: account {account.login} on {account.server} is a "
                "LIVE real-money account. Switch .env to a DEMO account, or - only if "
                "you accept the risk of real financial losses - set MT5_ALLOW_LIVE=1 "
                "in .env."
            )

        mode = TRADE_MODE_NAMES.get(account.trade_mode, f"unknown({account.trade_mode})")
        terminal = mt5.terminal_info()
        log(f"preflight OK: account {account.login} on {account.server} [{mode}]")
        if not (terminal and terminal.trade_allowed):
            log(
                "WARNING: algorithmic trading is disabled in MT5 "
                "(Tools > Options > Expert Advisors > Allow algorithmic trading). "
                "The MCP server will start, but order tools will be rejected."
            )
    finally:
        mt5.shutdown()


def main() -> int:
    check_only = "--check-only" in sys.argv
    extra_args = [arg for arg in sys.argv[1:] if arg != "--check-only"]

    if not os.path.isfile(ENV_FILE):
        fail(
            "No .env file found. Copy .env.example to .env and fill in your MT5 "
            "DEMO account credentials (login, password, server)."
        )

    env_values = load_env_file(ENV_FILE)
    login, password, server = get_credentials(env_values)
    missing = [name for name, value in (("login", login), ("password", password), ("server", server)) if not value]
    if missing:
        fail(f".env is missing: {', '.join(missing)}. Fill in your DEMO account credentials.")

    warn_if_env_is_tracked()

    # Expose credentials to the MCP server as environment variables (both the
    # lowercase names its lifespan reads and the documented uppercase aliases).
    os.environ.update(
        {
            "login": login,
            "password": password,
            "server": server,
            "LOGIN": login,
            "PASSWORD": password,
            "SERVER": server,
        }
    )

    preflight(login, password, server)

    if check_only:
        log("check-only: preflight passed. The MCP server would start now.")
        return 0

    # stdio is forced (appended last so it wins over any forwarded --transport).
    command = [sys.executable, "-m", "metatrader_mcp.server", *extra_args, "--transport", "stdio"]
    log("starting metatrader-mcp-server (stdio only, demo guard active)")
    return subprocess.run(command, cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
