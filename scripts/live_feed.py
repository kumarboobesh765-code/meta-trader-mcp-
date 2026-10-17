r"""Telegram live trade feed for the FTTest rig.

The forward_test runner calls notify(rows) with each batch of freshly
logged deals (entry=in opens, entry=out closes). Each batch becomes ONE
Telegram message (no per-deal spam) and appends compact events to
C:\FTTest\logs\feed.jsonl, which the web dashboard serves as its live tape.

Delivery mirrors overview_report.py: token from C:\VPSMonitor\telegram-token.txt
via PowerShell Invoke-RestMethod.
"""
import json
import os
import subprocess

TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
TAPE = r"C:\FTTest\logs\feed.jsonl"
TAPE_MAX = 200


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


def _tape_append(events):
    try:
        old = []
        if os.path.exists(TAPE):
            with open(TAPE, encoding="utf-8") as f:
                old = [ln for ln in f.read().splitlines() if ln.strip()]
        old.extend(json.dumps(e) for e in events)
        tmp = TAPE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(old[-TAPE_MAX:]) + "\n")
        os.replace(tmp, TAPE)
    except OSError:
        pass  # tape is cosmetic; never break the runner


def notify(rows):
    """rows = deals.csv-style dicts just logged by the runner."""
    if not rows:
        return
    msgs = ["FTTest live feed"]
    events = []
    for r in rows:
        if r["entry"] == "in":
            msgs.append("OPENED  %s  %s %.2f %s @ %.2f"
                        % (r["strategy"], r["type"], r["volume"],
                           r["symbol"], r["price"]))
        else:
            icon = "+" if r["profit"] >= 0 else "-"
            msgs.append("CLOSED%c %s  %.2f @ %.2f -> %+.2f"
                        % (icon, r["strategy"], r["volume"],
                           r["price"], r["profit"]))
        events.append({"ts": r["_ts"], "st": r["strategy"], "entry": r["entry"],
                       "type": r["type"], "vol": r["volume"], "price": r["price"],
                       "pnl": r["profit"]})
    _tape_append(events)
    send_telegram("\n".join(msgs))


def selftest():
    """Send one synthetic message + tape event (delivery-path check)."""
    import time as _t
    now = _t.time()
    row = {"time_utc": "", "ticket": 0, "magic": 0, "strategy": "selftest",
           "position_id": 0, "symbol": "XAUUSD", "type": "buy", "entry": "in",
           "volume": 0.01, "price": 4142.0, "commission": 0.0, "swap": 0.0,
           "profit": 0.0, "comment": "test", "_ts": now}
    notify([row])
    print("selftest sent (check Telegram)")


if __name__ == "__main__":
    selftest()
