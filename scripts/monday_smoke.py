r"""Monday-open smoke test for the Vantage forward test. Runs ON THE VPS.

Fires weekly (task FTMondaySmoke) Monday 12:20 server time -- after the
open, so fills/pendings exist -- or run manually any time:
  schtasks /TN FTMondaySmoke /TR "<python> C:\FTTest\scripts\monday_smoke.py"
    /SC WEEKLY /D MON /ST 12:20

One consolidated Telegram report covering:
  1. terminal up, account = the .env login (Vantage 26122844)
  2. deals.csv / equity.csv exist with data rows and are FRESH (today);
     the first deals row is reported as (what should be) the first
     Vantage fill -- the runner logs started clean at the account switch
  3. straddle/london runner slots: dual stops ARMED (pendings), or FILLED
     (position), or already TRADED this server day -- only a slot with
     none of those is a problem. Sat/Sun it just reports and exits 0
     (market closed: empty CSVs and no pendings are EXPECTED).
  4. runner stdout tail: no 10015/10016 (invalid price/stops) or 10027
     (algo disabled); 10012/10018/10004 are transient and expected
  5. runner process actually alive

Exit code 0 = clean (or weekend), 1 = problems found.
"""

import csv
import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import (SYMBOLS, STRAT_NAMES, SERVER_TIME_OFFSET, load_env)

# EA-only rig: dual-stop slots are traded by the EAs, so health checks use
# EA magics. XAU-ONLY RIG (2026-09-28): the FX book (FTTestMultiEA on chart
# 15, bases 931000-934000) was retired -- only the XAUUSD base remains.
# strat index: breakout1 meanrev2 macross3 straddle4 smc5 london6 squeeze7
EA_BASE = {"XAUUSD": 930000}
DUAL_INDICES = (4, 6)  # straddle, london

LOG_DIR = r"C:\FTTest\logs"
DEALS_CSV = os.path.join(LOG_DIR, "forward", "deals.csv")
EQUITY_CSV = os.path.join(LOG_DIR, "forward", "equity.csv")
RUNNER_STDOUT = os.path.join(LOG_DIR, "forward_test_stdout.txt")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

# transient retcodes a demo around the weekend/open boundary throws by design
TRANSIENT = ("10012", "10018", "10004")
# hard failures that mean real trouble (bad prices/stops, algo disabled...)
HARD_FAILS = ("10015", "10016", "10027")


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def runner_alive():
    # NOTE: wmic is REMOVED on this Windows Server build -> FileNotFoundError;
    # CIM via powershell is the reliable way to see python command lines.
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\""
              " | ForEach-Object { $_.CommandLine }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True,
                             errors="replace").stdout.lower()
        return "forward_test.py" in out
    except Exception:
        return False


def tail(path, nbytes=400000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - nbytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def csv_rows(path):
    try:
        with open(path, newline="") as f:
            return list(csv.reader(f))
    except OSError:
        return []


def main():
    problems, notes = [], []
    acc_login, server = None, "?"
    weekend = datetime.now().weekday() >= 5  # Sat/Sun on the VPS clock

    if not mt5.initialize():
        send_telegram("FTSmoke: mt5.initialize FAILED %s -- terminal down?"
                      % (mt5.last_error(),))
        return 1
    try:
        acc = mt5.account_info()
        if acc is None:
            problems.append("no account session (IPC dead)")
        else:
            acc_login, server = acc.login, acc.server

        env = load_env()
        want = int(env.get("login", "0") or 0)
        if acc_login is not None and acc_login != want:
            problems.append("account %s != .env login %s" % (acc_login, want))

        # ---- 2. CSVs ------------------------------------------------------
        deals = csv_rows(DEALS_CSV)
        eq = csv_rows(EQUITY_CSV)
        if len(deals) < 2:
            if weekend:
                notes.append("deals.csv still empty (weekend, expected)")
            else:
                problems.append("deals.csv has no data rows yet")
        else:
            # DEAL_FIELDS: 0 time_utc, 1 ticket, 2 magic, 3 strategy, 4 pos_id,
            # 5 symbol, 6 type, 7 entry, 8 volume, 9 price.
            first = deals[1]
            notes.append("deals.csv first fill: %s %s %s %s vol=%s @ %s"
                         % (first[5], first[3], first[6], first[7],
                            first[8], first[9] if len(first) > 9 else "?"))
            last_deal_min = (time.time() - os.path.getmtime(DEALS_CSV)) / 60.0
            if weekend:
                notes.append("deals.csv: %d rows, last write %.0f min ago"
                             % (len(deals) - 1, last_deal_min))
            elif last_deal_min > 180:
                problems.append("deals.csv stale: no writes for %.0f min"
                                % last_deal_min)
        if len(eq) < 2:
            if not weekend:
                problems.append("equity.csv has no data rows yet")
        else:
            last_eq_min = (time.time() - os.path.getmtime(EQUITY_CSV)) / 60.0
            if not weekend and last_eq_min > 30:
                problems.append("equity.csv stale: no writes for %.0f min"
                                % last_eq_min)

        # ---- 3. dual-stop slots (EA magics: straddle=idx4, london=idx6) ---
        now_local = time.time()
        server_day_start = ((now_local + SERVER_TIME_OFFSET) // 86400) * 86400 \
            - SERVER_TIME_OFFSET
        todays = mt5.history_deals_get(server_day_start, now_local + 4 * 3600) or []
        for sym in EA_BASE:   # XAU-only rig: EA_BASE drives the symbol list
            base0 = EA_BASE[sym]
            for i in DUAL_INDICES:
                name = STRAT_NAMES[i - 1]
                magic = base0 + i
                magics = (magic, magic + 10000)  # fixed + trailing twin
                if any(p.magic in magics
                       for p in (mt5.positions_get(symbol=sym) or [])):
                    notes.append("%s %s: FILLED (position open)" % (sym, name))
                    continue
                pens = [o for o in (mt5.orders_get(symbol=sym) or [])
                        if o.magic in magics]
                if pens:
                    notes.append("%s %s: ARMED (%d pending)"
                                 % (sym, name, len(pens)))
                    continue
                if any(d.magic in magics and d.entry == mt5.DEAL_ENTRY_IN
                       for d in todays):
                    notes.append("%s %s: already traded this day" % (sym, name))
                    continue
                if weekend:
                    notes.append("%s %s: idle (weekend, expected)"
                                 % (sym, name))
                else:
                    problems.append("%s %s: no pendings, no position, "
                                    "no fills today" % (sym, name))

        # ---- 4. runner log tail -------------------------------------------
        chunk = tail(RUNNER_STDOUT)
        # only the CURRENT runner session matters: older sessions in the tail
        # can still contain dead-IPC loop errors / weekend order-fail spam
        last_start = chunk.rfind("forward test STARTED")
        if last_start > 0:
            chunk = chunk[last_start:]
        hard = [rc for rc in HARD_FAILS if ("retcode=%s" % rc) in chunk]
        trans = {rc: chunk.count("retcode=%s" % rc) for rc in TRANSIENT
                 if ("retcode=%s" % rc) in chunk}
        if hard:
            problems.append("hard order-fails in runner log: %s"
                            % ",".join(hard))
        if "loop error" in chunk:
            problems.append("runner loop errors present")
        if trans:
            notes.append("transient retcodes (ok): %s"
                         % ", ".join("%s x%d" % kv
                                     for kv in sorted(trans.items())))

        # ---- 5. runner process --------------------------------------------
        if not runner_alive():
            problems.append("forward_test.py runner process NOT running")
    finally:
        mt5.shutdown()

    tag = " (weekend preview)" if weekend else ""
    msg = "FTSmoke %s%s: %s (acc=%s server=%s)" % (
        datetime.now().strftime("%d.%m %H:%M"), tag,
        "OK" if not problems else "PROBLEMS", acc_login, server)
    if problems:
        msg += "\nPROBLEMS:\n- " + "\n- ".join(problems[:8])
    if notes:
        msg += "\nNotes:\n- " + "\n- ".join(notes[:12])
    print(msg, flush=True)
    send_telegram(msg)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
