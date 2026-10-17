r"""Daily Telegram digest for the FTTest rig (08:00 UTC via FTDigest task).

Deliberately FILE-BASED (deals.csv + live.json): no MT5 attach, so it works
even when fresh terminal attaches are refused to scheduled processes.
live.json is the runner's 30s-fresh snapshot (balance/equity/open/floating).
"""
import csv
import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

LOG = r"C:\FTTest\logs"
DEALS = os.path.join(LOG, "forward", "deals.csv")
LIVE = os.path.join(LOG, "live.json")
TRAIL_JSON = os.path.join(LOG, "trail_audit.json")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
DASH_URL = "http://109.122.56.70:8090/ft26122844/"

# the 31 live EAs (2026-09-30 rig) + retired magics still in the log
ROSTER = [
    (930001, "breakout"), (940001, "breakout-T"),
    (930003, "macross"), (940003, "macross-T"),
    (930004, "straddle"), (940004, "straddle-T"),
    (930005, "smc"), (940005, "smc-T"),
    (930006, "london"), (940006, "london-T"),
    (930007, "squeeze"), (940007, "squeeze-T"),
    (930009, "fixfade"), (940009, "fixfade-T"),   # repurposed from orderflow 10/01
    (930011, "donchian"), (940011, "donchian-T"),
    (930012, "trend"), (940012, "trend-T"),
    (930013, "vwaprev"), (940013, "vwaprev-T"),   # repurposed from supres 10/01
    (930014, "supertrend"), (940014, "supertrend-T"),
    (930015, "liquiditysweep-EA"), (930016, "liquiditysweep-BIN"),
    (930017, "dayopen"),   # added 2026-10-02
    (950001, "aetherflow"), (960001, "aetherflow-T"),
    (950002, "aetherflow-M30"), (960002, "aetherflow-M30-T"),
    (950003, "aetherflow-H4"), (960003, "aetherflow-H4-T"),
    (26092501, "smvp"),
]
RETIRED_MAGICS = {930002, 940002, 930008, 940008, 930010, 940010}
RETIRED_NAMES = {930002: "meanrev(R)", 940002: "meanrev-T(R)",
                 930008: "profile(R)", 940008: "profile-T(R)",
                 930010: "trendpullback(R)", 940010: "trendpullback-T(R)"}


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
    if s.startswith("aetherflow-"):
        return "aetherflow"
    return s


def main():
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sess = defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0, "gp": 0.0, "gl": 0.0})
    today = defaultdict(float)
    today_n = 0
    with open(DEALS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["entry"] != "out":
                continue
            pnl = float(row["profit"] or 0) + float(row["commission"] or 0) + float(row["swap"] or 0)
            s = sess[family(row["strategy"])]
            s["n"] += 1
            s["net"] += pnl
            if pnl > 0:
                s["wins"] += 1
                s["gp"] += pnl
            elif pnl < 0:
                s["gl"] += -pnl
            if row["time_utc"][:10] == day:
                today[family(row["strategy"])] += pnl
                today_n += 1
    total_n = sum(s["n"] for s in sess.values())
    total_net = sum(s["net"] for s in sess.values())
    gp = sum(s["gp"] for s in sess.values())
    gl = sum(s["gl"] for s in sess.values())
    pf = ("%.2f" % (gp / gl)) if gl > 0 else "inf"
    day_net = sum(today.values())

    live = {}
    try:
        with open(LIVE, encoding="utf-8") as f:
            live = json.load(f)
    except (OSError, ValueError):
        pass

    lines = ["FTTest daily digest -- %s" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]
    if live:
        lines.append("Balance %s | Equity %s | open %s (float %s)"
                     % (live.get("bal", "?"), live.get("eq", "?"),
                        live.get("open", "?"), live.get("flt", "?")))
    lines.append("Session: %+.2f across %d trips | PF %s" % (total_net, total_n, pf))
    lines.append("Today UTC: %+.2f (%d trips)" % (day_net, today_n))
    if today:
        for name, net in sorted(today.items(), key=lambda kv: -kv[1])[:4]:
            lines.append("  top: %-14s %+.2f" % (name, net))
        worst = sorted(today.items(), key=lambda kv: kv[1])[:2]
        for name, net in worst:
            if net < 0:
                lines.append("  weak: %-14s %+.2f" % (name, net))
    lines.append("Live dashboard: %s" % DASH_URL)

    # ---- per-EA roster: every EA, closed trips + today (file-based) -------
    trips = {}       # magic -> [n, net, wins, today_net, gp, gl]
    pos_in = {}
    with open(DEALS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                m = int(row["magic"])
                pnl = float(row["profit"] or 0) + float(row["commission"] or 0) \
                    + float(row["swap"] or 0)
            except (ValueError, KeyError):
                continue
            if row["entry"] == "in":
                pos_in[row["position_id"]] = m
            elif row["entry"] == "out" and row["position_id"] in pos_in:
                t = trips.setdefault(m, [0, 0.0, 0, 0.0, 0.0, 0.0])
                t[0] += 1
                t[1] += pnl
                t[2] += 1 if pnl > 0 else 0
                if pnl > 0:
                    t[4] += pnl
                elif pnl < 0:
                    t[5] -= pnl
                if row["time_utc"][:10] == day:
                    t[3] += pnl
    roster = list(ROSTER) + [(m, RETIRED_NAMES[m]) for m in sorted(RETIRED_MAGICS)]
    lines.append("=== LIVE EA ROSTER (closed trips, session) ===")
    rows = []
    for m, name in roster:
        n, net, wins, tday, gp, gl = trips.get(m, [0, 0.0, 0, 0.0, 0.0, 0.0])
        pf = ("%.2f" % (gp / gl)) if gl > 0 else ("inf" if gp > 0 else "-")
        w = 100.0 * wins / n if n else 0.0
        rows.append((net, name, n, pf, w, tday))
    for net, name, n, pf, w, tday in sorted(rows, key=lambda x: -x[0]):
        if n == 0 and abs(net) < 0.005:
            continue                     # silent EAs keep the message short
        lines.append("%-18s %4d %+8.2f %-5s %3.0f%% t%+7.2f"
                     % (name, n, net, pf, w, tday))
    quiet = [name for net, name, n, pf, w, tday in sorted(rows, key=lambda x: -x[0])
             if n == 0 and abs(net) < 0.005]
    if quiet:
        lines.append("quiet (no closed trips): %s" % ", ".join(quiet))

    # ---- trailing-SL health (written hourly by _diag_trail_audit --json) ---
    try:
        ta = json.load(open(TRAIL_JSON, encoding="utf-8"))
        age_h = (__import__("time").time() - ta.get("ts", 0)) / 3600.0
        lines.append("--- TRAIL HEALTH (%.1fh old, 0.2/0.5/0.10 deployed) ---"
                     % age_h)
        lines.append("armed=%d waiting=%d SUSPICIOUS=%d fixed-violations=%d"
                     % (ta.get("armed", 0), ta.get("waiting", 0),
                        ta.get("suspicious", 0), ta.get("fixed_bad", 0)))
        for ln in ta.get("lines", [])[-5:]:
            lines.append("  " + ln)
    except (OSError, ValueError):
        lines.append("TRAIL HEALTH: no recent audit (trail_audit.json missing)")

    msg = "\n".join(lines)
    ok = send_telegram(msg)
    print(("digest sent OK" if ok else "digest SEND FAILED") + ":\n" + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
