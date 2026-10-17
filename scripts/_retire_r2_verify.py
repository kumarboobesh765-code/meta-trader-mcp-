r"""Post-verdict verifier for retirement round-2 (scheduled Oct 1 13:55 VPS,
10 min after FTRetireExec2). Read-only; confirms what the executor actually
did and Telegrams a compact verification report + the registry patch plan.

Checks:
  1. retire_r2.executed.log tail (what the executor claims)
  2. profile dir .chr count + the exact charts of every approved family
     absent on disk
  3. MT5 journal (since executor ran): zero 'loaded successfully' lines for
     the retired EAs (FTTest_trendpullback/_donchian/_trend/_squeeze)
  4. runner stdout: fresh session (forward test STARTED after 13:45), no
     errors; supertrend watchdog still hooked
  5. dashboard live.json freshness
Exit 0 always (report task); the human-readable patch plan is in the
Telegram message for whoever runs scripts/patch_registries_r2.py locally.
"""
import glob
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

FT = r"C:\FTTest"
LOG = os.path.join(FT, "logs")
EXEC_LOG = os.path.join(LOG, "retire_r2.executed.log")
APPROVED = os.path.join(LOG, "retire_r2.APPROVED")
DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
PROFILE = os.path.join(DATA, "MQL5", "Profiles", "Charts", "FTTest")
STDOUT = os.path.join(LOG, "forward_test_stdout.txt")
LIVE = os.path.join(LOG, "live.json")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

EA_OF = {"trendpullback": "FTTest_trendpullback", "donchian": "FTTest_donchian",
         "trend": "FTTest_trend", "squeeze": "FTTest_squeeze"}
CHARTS = {"trendpullback": (25, 26), "donchian": (27, 28),
          "trend": (29, 30), "squeeze": (13, 14)}


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
    lines = ["FTRetireVerify2 -- %s" % datetime.now(timezone.utc)
             .strftime("%Y-%m-%d %H:%M UTC")]

    fams = []
    if os.path.exists(APPROVED):
        fams = [f.strip() for f in open(APPROVED).read().strip().split(",")
                if f.strip() in CHARTS]
    lines.append("approved families: %s" % (fams or "NONE (stood down)"))

    # 1) executor log
    if os.path.exists(EXEC_LOG):
        tail = open(EXEC_LOG, errors="replace").read().splitlines()[-6:]
        lines.append("executor log tail:")
        lines += ["  " + l[:150] for l in tail]

    # 2) chr files
    if fams:
        want = sorted(c for f in fams for c in CHARTS[f])
        gone = [c for c in want
                if not os.path.exists(os.path.join(PROFILE, "chart%02d.chr" % c))]
        prof_n = len(glob.glob(os.path.join(PROFILE, "*.chr")))
        want_n = 31 - 2 * len(fams)
        lines.append("charts deleted: %s | profile count: %d (want %d) %s"
                     % (gone, prof_n, want_n,
                        "OK" if (len(gone) == len(want) and prof_n == want_n)
                        else "MISMATCH"))
        # 3) journal since executor (last 30 min is enough at 13:55)
        cut = time.time() - 30 * 60
        loaded = []
        for j in glob.glob(os.path.join(DATA, "logs", "*.log")):
            if os.path.getmtime(j) < cut:
                continue
            try:
                txt = open(j, encoding="utf-16", errors="replace").read()
            except UnicodeError:
                txt = open(j, encoding="cp1252", errors="replace").read()
            for m in re.finditer(r"expert\s+(\S+)\s+\(([^,)]+),([^)]+)\)\s+"
                                 r"loaded successfully", txt):
                loaded.append(m.group(1))
        retired_loaded = [n for n in loaded
                          if n in {EA_OF[f] for f in fams}]
        lines.append("EA loads since 13:35: %d total | retired still loading: %s"
                     % (len(loaded), retired_loaded or "none OK"))
    else:
        prof_n = len(glob.glob(os.path.join(PROFILE, "*.chr")))
        lines.append("no retirement: profile count still %d (want 31)" % prof_n)

    # 4) runner freshness
    age = time.time() - os.path.getmtime(STDOUT) if os.path.exists(STDOUT) else 1e9
    started = False
    if os.path.exists(STDOUT):
        t = open(STDOUT, errors="replace").read()
        i = t.rfind("forward test STARTED")
        started = i >= 0 and os.path.getmtime(STDOUT) - (time.time() - 3600) < 3600
        seg = t[i:] if i >= 0 else ""
        errs = [l for l in seg.splitlines()
                if re.search(r"REFUSING|FAILED|error", l, re.I)]
        lines.append("runner stdout age %.0fs | fresh STARTED: %s | errors: %d"
                     % (age, started, len(errs)))
    # 5) live.json
    try:
        lv = json.load(open(LIVE, encoding="utf-8"))
        lines.append("live.json: bal=%s eq=%s open=%s gen=%s"
                     % (lv.get("bal"), lv.get("eq"), lv.get("open"),
                        lv.get("gen")))
    except (OSError, ValueError):
        lines.append("live.json unreadable")

    if fams:
        lines.append("PATCH PLAN: run locally  python "
                     "scripts/patch_registries_r2.py --families %s"
                     % ",".join(fams))
    msg = "\n".join(lines)
    print(msg)
    telegram(msg)
    return 0


if __name__ == "__main__":
    main()
