r"""Round-2 retirement EXECUTOR (2026-10-01, runs 13:45 after FTRetireGate2).

Only acts if the gate wrote C:\FTTest\logs\retire_r2.APPROVED (comma-separated
family names). For each approved family:
  1. market-close any open positions on its two magics (MT5 attach, best-effort)
  2. taskkill terminal64 -> re-delete the family's chart .chr files (MT5 can
     flush the profile on exit) -> mt_relaunch.ps1 (schtasks console-session
     trick) so the charts never come back
  3. Telegram a per-family result + append to retire_r2.executed.log
No APPROVED marker (gate said KEEP / PENDING) -> stand-down Telegram note,
zero side effects.

Registry cleanup (forward_test MAGICS stay by design; champion_check/
make_ea_profile/_diag expected lists) is done in the repo afterwards.

Run: python C:/FTTest/scripts/_retire_r2_execute.py        (scheduled mode)
     python C:/FTTest/scripts/_retire_r2_execute.py --dry  (validate, no side effects)
"""
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "C:/FTTest/scripts")

FT = r"C:\FTTest"
LOG = os.path.join(FT, "logs")
APPROVED = os.path.join(LOG, "retire_r2.APPROVED")
EXEC_LOG = os.path.join(LOG, "retire_r2.executed.log")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
PROFILE = os.path.join(DATA, "MQL5", "Profiles", "Charts", "FTTest")

# family -> (charts, magics)
PLAN = {
    "trendpullback": ((25, 26), (930010, 940010)),
    "donchian":      ((27, 28), (930011, 940011)),
    "trend":         ((29, 30), (930012, 940012)),
    "squeeze":       ((13, 14), (930007, 940007)),
}


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def log(msg):
    line = "%s %s" % (datetime.now(timezone.utc).isoformat(), msg)
    print(line, flush=True)
    with open(EXEC_LOG, "a") as f:
        f.write(line + "\n")


def close_positions(magics):
    import MetaTrader5 as mt5
    from forward_test import load_env
    load_env()
    for attempt in range(4):
        if mt5.initialize():
            break
        mt5.shutdown()
        time.sleep(6)
    else:
        return "mt5 attach FAILED -- open positions left (watchdog still active)"
    closed = []
    try:
        for p in (mt5.positions_get() or []):
            if p.magic not in magics:
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket,
                   "symbol": p.symbol, "volume": p.volume,
                   "type": (mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY
                            else mt5.ORDER_TYPE_BUY),
                   "price": (tick.bid if p.type == mt5.POSITION_TYPE_BUY
                             else tick.ask),
                   "deviation": 100, "magic": p.magic,
                   "comment": "retire r2", "type_filling": mt5.ORDER_FILLING_IOC}
            r = mt5.order_send(req)
            ok = r is not None and r.retcode == 10009
            closed.append("#%d m%d %s" % (p.ticket, p.magic,
                                          "ok" if ok else "FAIL ret=%s"
                                          % (getattr(r, "retcode", "?"))))
    finally:
        mt5.shutdown()
    return "closed: %s" % (", ".join(closed) if closed else "none were open")


def main():
    dry = "--dry" in sys.argv
    if not os.path.exists(APPROVED):
        msg = ("FTRetireExec2: no APPROVED marker -> STANDING DOWN "
               "(gate kept all four or window still pending). No charts touched.")
        print(msg)
        if not dry:
            send_telegram(msg)
        return 0
    fams = [f.strip() for f in open(APPROVED).read().strip().split(",") if f.strip()]
    fams = [f for f in fams if f in PLAN]
    if not fams:
        print("APPROVED file has no actionable families:", fams)
        return 0

    results = []
    charts_all = []
    for f in fams:
        charts, magics = PLAN[f]
        charts_all += list(charts)
        if dry:
            results.append("%s DRY (charts %s)" % (f, charts))
            continue
        res = close_positions(magics)
        log("retire r2 %s positions -> %s" % (f, res))
        results.append("%s: %s" % (f, res))

    if dry:
        print("DRY: would delete charts", charts_all, "| results:", results)
        return 0

    # kill MT5, re-delete chr (exit flush), relaunch in console session
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"],
                   capture_output=True)
    time.sleep(6)
    deleted, missing = [], []
    for c in charts_all:
        p = os.path.join(PROFILE, "chart%02d.chr" % c)
        if os.path.exists(p):
            os.remove(p)
            deleted.append(c)
        else:
            missing.append(c)
    log("deleted chr: %s (already absent: %s)" % (deleted, missing))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", os.path.join(FT, "mt_relaunch.ps1")],
                   capture_output=True, timeout=90)
    msg = ("FTRetireExec2: RETIRED %s -- charts %s deleted, MT5 relaunching. "
           "Runner respawns within 60s. | %s"
           % (",".join(fams), deleted, "; ".join(results)))
    log(msg)
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
