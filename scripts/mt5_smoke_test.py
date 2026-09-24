#!/usr/bin/env python3
"""Repeatable smoke test for the MetaTrader MCP + safety guard.

Verifies, in order:
  1. Credential hygiene: .env exists, is git-ignored, and is not tracked.
  2. Safety guard pre-flight: MT5 must ALREADY be open (this test NEVER
     launches MetaTrader 5 - it fails with a message asking you to open it),
     and the connected account must be a DEMO/contest account.
  3. MCP stdio handshake through the guarded launcher Freebuff uses.
  4. All expected trading tools are exposed.
  5. get_account_info works and reports the account type correctly.

Usage:
    python scripts/mt5_smoke_test.py

Exit code 0 = all checks passed. Re-run after any change to the setup.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "mt5_mcp_guarded.py")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

EXPECTED_TOOLS = [
    "get_account_info",
    "get_symbol_price",
    "get_candles_latest",
    "get_all_symbols",
    "get_symbols",
    "get_all_positions",
    "get_positions_by_symbol",
    "get_positions_by_id",
    "get_all_pending_orders",
    "get_pending_orders_by_symbol",
    "get_pending_orders_by_id",
    "place_market_order",
    "place_pending_order",
    "modify_position",
    "modify_pending_order",
    "close_position",
    "close_all_positions",
    "close_all_positions_by_symbol",
    "close_all_profitable_positions",
    "close_all_losing_positions",
    "cancel_pending_order",
    "cancel_all_pending_orders",
    "cancel_pending_orders_by_symbol",
    "get_deals",
    "get_orders",
]

RESULTS: list[tuple[str, str]] = []


def record(status: str, message: str) -> None:
    RESULTS.append((status, message))
    print(f"[{status}] {message}", flush=True)


def check_credential_hygiene() -> bool:
    if not os.path.isfile(ENV_FILE):
        record("FAIL", ".env is missing - copy .env.example to .env and fill in demo credentials")
        return False
    try:
        tracked = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "ls-files", "--", ".env"],
            capture_output=True, text=True, timeout=20,
        )
        ignored = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "check-ignore", "-q", ".env"],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        record("WARN", f"could not verify git status of .env ({exc})")
        return True
    if tracked.stdout.strip():
        record("FAIL", "CREDENTIAL LEAK: .env is tracked by git (git rm --cached .env)")
        return False
    if ignored.returncode != 0:
        record("WARN", ".env is not git-ignored - add it to .gitignore")
    else:
        record("PASS", ".env exists and is git-ignored (no credential leak)")
    with open(ENV_FILE, "r", encoding="utf-8") as fh:
        if "MT5_ALLOW_LIVE=1" in fh.read().replace(" ", ""):
            record("WARN", "MT5_ALLOW_LIVE=1 is set - live trading is explicitly enabled!")
    return True


def check_guard_preflight() -> bool:
    """Runs the guard's own pre-flight. NEVER launches MT5."""
    try:
        proc = subprocess.run(
            [sys.executable, GUARD_SCRIPT, "--check-only"],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        record("FAIL", "guard pre-flight timed out")
        return False
    stderr = proc.stderr
    if proc.returncode == 0 and "[DEMO]" in stderr or proc.returncode == 0 and "[CONTEST]" in stderr:
        account_line = next((l for l in stderr.splitlines() if "preflight OK" in l), "")
        record("PASS", f"guard pre-flight: {account_line.split('] ', 1)[-1]}")
        return True
    if "NOT running" in stderr:
        record("FAIL", "MetaTrader 5 is not open - open MT5 manually and re-run this test (it will never be launched for you)")
    elif "LIVE real-money" in stderr:
        record("FAIL", "guard refused a LIVE account (this is the guard working as designed)")
    else:
        record("FAIL", f"guard pre-flight failed: {stderr.strip() or 'no error output'}")
    return False


async def run_mcp_checks() -> bool:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[GUARD_SCRIPT, "--transport", "stdio"],
        env=dict(os.environ),
    )
    ok = True
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            record("PASS", "MCP stdio handshake through the guarded launcher")

            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            missing = [t for t in EXPECTED_TOOLS if t not in names]
            if missing:
                record("FAIL", f"missing expected tools: {', '.join(missing)}")
                ok = False
            else:
                record("PASS", f"all {len(EXPECTED_TOOLS)} expected trading tools exposed ({len(names)} total)")
            extra = [n for n in names if n not in EXPECTED_TOOLS]
            if extra:
                record("WARN", f"unexpected tools present: {', '.join(extra)}")

            result = await session.call_tool("get_account_info", {})
            payload = json.loads(result.content[0].text)
            if isinstance(payload.get("balance"), (int, float)):
                record("PASS", f"get_account_info OK (balance {payload['balance']} {payload.get('currency', '')})")
            else:
                record("FAIL", f"get_account_info returned unexpected data: {payload}")
                ok = False
            if payload.get("account_type") == "demo":
                record("PASS", "account_type correctly reports 'demo' (mislabel bug is fixed)")
            else:
                record("FAIL", f"account_type reports {payload.get('account_type')!r} - expected 'demo' (mislabel bug is back?)")
                ok = False
    return ok


def main() -> int:
    print("=== MetaTrader MCP smoke test (this test never launches MT5) ===")
    if not check_credential_hygiene():
        return summarize()
    if not check_guard_preflight():
        return summarize()
    try:
        mcp_ok = asyncio.run(asyncio.wait_for(run_mcp_checks(), timeout=180))
    except Exception as exc:  # noqa: BLE001 - report any failure clearly
        record("FAIL", f"MCP checks failed: {exc}")
        mcp_ok = False
    return summarize() if mcp_ok else summarize()


def summarize() -> int:
    passed = sum(1 for status, _ in RESULTS if status == "PASS")
    failed = sum(1 for status, _ in RESULTS if status == "FAIL")
    warned = sum(1 for status, _ in RESULTS if status == "WARN")
    print(f"=== {passed} passed, {failed} failed, {warned} warnings ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
