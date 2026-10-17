r"""24h retirement-confirmation gate for round-2 bleeders (2026-10-01 run).

Families on trial: trendpullback, donchian, squeeze, trend (both twins each).
Final 24h confirmation demanded by the user before deleting charts 25-30.

Deliberately FILE-BASED (deals.csv, no MT5 attach -- same pattern as the
daily digest). Verdict per family over the 24h window since the gate was
armed (armed_ts written by the caller / default = last 24h of log):
  RETIRE   if session net < 0  OR  >= 60% of its daily nets are negative
  KEEP     otherwise (probation extended one more day, task re-schedules)

Writes C:\FTTest\logs\retire_r2.APPROVED / .REJECTED with the families, so
the human-run retirement step can gate on it. Telegram either way.

Run: schtasks /TN FTRetireGate2 /TR "python C:\FTTest\scripts\_retire_r2_gate.py"
"""
import csv
import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

LOG = r"C:\FTTest\logs"
DEALS = os.path.join(LOG, "forward", "deals.csv")
MARKER = os.path.join(LOG, "retire_r2.armed_ts")
APPROVED = os.path.join(LOG, "retire_r2.APPROVED")
REJECTED = os.path.join(LOG, "retire_r2.REJECTED")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

FAMILIES = ("trendpullback", "donchian", "squeeze", "trend")


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


def family(stream):
    s = stream
    for suf in ("-EA-T", "-EA", "-T"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s


def main():
    # armed timestamp = when the trial started (default: now-24h)
    try:
        armed = float(open(MARKER).read().strip())
    except (OSError, ValueError):
        armed = (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
        with open(MARKER, "w") as f:
            f.write(str(armed))
    day_nets = defaultdict(lambda: defaultdict(float))   # family -> day -> net
    with open(DEALS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["entry"] != "out":
                continue
            fam = family(r["strategy"])
            if fam not in FAMILIES:
                continue
            day = r["time_utc"][:10]
            day_nets[fam][day] += float(r["profit"] or 0) + \
                float(r["commission"] or 0) + float(r["swap"] or 0)

    verdicts = {}
    for fam in FAMILIES:
        days = {d: v for d, v in day_nets[fam].items()
                if datetime.fromisoformat(d + "T00:00:00+00:00").timestamp() >= armed}
        net24 = sum(days.values())
        if not days:
            verdicts[fam] = ("PENDING", 0.0, 0.0)   # empty window: no data yet
            continue
        neg_share = sum(1 for v in days.values() if v < 0) / len(days)
        verdicts[fam] = ("RETIRE", net24, neg_share) \
            if (net24 < 0 or neg_share >= 0.6) else ("KEEP", net24, neg_share)

    retiring = [f for f, (v, n, s) in verdicts.items() if v == "RETIRE"]
    keeping = [f for f, (v, n, s) in verdicts.items() if v == "KEEP"]
    for f, (v, n, s) in verdicts.items():
        print("%-14s %-6s 24h=%+8.2f neg_days=%.0f%%" % (f, v, n, 100 * s))

    detail = " | ".join("%s %s(%+.2f)" % (f, verdicts[f][0], verdicts[f][1])
                        for f in FAMILIES)
    if any(v == "PENDING" for v, _, _ in verdicts.values()):
        with open(REJECTED, "w") as f:
            f.write("PENDING")
        ok = send_telegram("FTRetireGate2: window not populated yet -- no verdict "
                           "(gate re-runs; chart deletion stays blocked) | %s" % detail)
        print("PENDING -- no verdict")
        print("telegram:", "OK" if ok else "FAILED")
        return 0
    if retiring:
        with open(APPROVED, "w") as f:
            f.write(",".join(retiring))
        ok = send_telegram("FTRetireGate2: CONFIRMED -> %s | %s | delete charts "
                           "25-30 when ready (pipeline ready, awaiting go)"
                           % (",".join(retiring), detail))
        print("APPROVED for:", ",".join(retiring))
    else:
        with open(REJECTED, "w") as f:
            f.write(",".join(keeping))
        ok = send_telegram("FTRetireGate2: NO CONFIRMATION -- all four stay on "
                           "probation | %s" % detail)
        print("probation extended for all")
    print("telegram:", "OK" if ok else "FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
