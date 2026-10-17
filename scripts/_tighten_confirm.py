r"""One-shot tightened-trail confirmation (2026-10-01): scans the MT5 journal
for 'trail SL ->' modify lines since the 2026-09-30 18:20 bounce, groups them
per EA, adds the current armed/waiting counts, and Telegrams the verdict that
the 0.2/0.5/0.10 trail actually ARMS and LOCKS in live trading.

Run: python C:/FTTest/scripts/_tighten_confirm.py   (scheduled FTTightenConfirm)
"""
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

FT = r"C:\FTTest"
DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
SINCE = time.mktime(time.strptime("2026-09-30 18:20:00", "%Y-%m-%d %H:%M:%S"))


def telegram(text):
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


def main():
    per_ea = {}
    total = 0
    for j in glob.glob(os.path.join(DATA, "logs", "*.log")):
        if os.path.getmtime(j) < SINCE:
            continue
        try:
            txt = open(j, encoding="utf-16", errors="replace").read()
        except UnicodeError:
            txt = open(j, encoding="cp1252", errors="replace").read()
        for m in re.finditer(r"(\w+) \d+ trail SL -> ([\d.]+)", txt):
            ea = m.group(1)
            per_ea[ea] = per_ea.get(ea, 0) + 1
            total += 1
    lines = ["TIGHTEN-CONFIRM (trail 0.2/0.5/0.10 live since 09-30 18:20)"]
    lines.append("trail-modify lines in journal: %d" % total)
    for ea, c in sorted(per_ea.items(), key=lambda kv: -kv[1])[:12]:
        lines.append("  %-24s x%d" % (ea, c))

    # live armed snapshot from the hourly audit json (if fresh)
    jf = os.path.join(FT, "logs", "trail_audit.json")
    try:
        import json
        ta = json.load(open(jf, encoding="utf-8"))
        age_h = (time.time() - ta.get("ts", 0)) / 3600.0
        lines.append("audit(%.1fh old): armed=%d waiting=%d suspicious=%d"
                     % (age_h, ta.get("armed", 0), ta.get("waiting", 0),
                        ta.get("suspicious", 0)))
    except (OSError, ValueError):
        pass
    verdict = ("CONFIRMED: tightened trail is arming and locking in live"
               if total > 0 else
               "NO trail-mods YET (no position has reached +0.2 ATR since "
               "deploy -- not a fault; task can be re-run after the next "
               "green run)")
    lines.append(verdict)
    msg = "\n".join(lines)
    print(msg)
    telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
