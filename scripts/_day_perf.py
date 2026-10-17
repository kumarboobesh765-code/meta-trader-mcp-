"""Daily per-strategy performance report to Telegram (plain language).

Answers the user's request (2026-10-01): "send me day performance by
strategies on telegram that i can understand easily".

File-based ONLY (deals.csv + live.json) -- never attaches to MT5, so it can
run at any hour without touching the runner's IPC. Scheduled as FTDayPerf
daily 23:00 VPS time (= end of the gold trading day).

Message layout:
  header (balance / today / open + floating)
  Winners  / Losers  with $ and plain-language state
  Quiet    (no trades today -- normal, nothing wrong)
  one-line bottom line (biggest winner, biggest loser, notes)

Run on the VPS: C:/PROGRA~1/Python314/python.exe C:/FTTest/scripts/_day_perf.py
  [--date YYYY-MM-DD]  (default: today UTC)  [--json path]
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

# emoji-rich messages crash the cp1252 VPS console on print -- replace, don't
# fail (Telegram still receives the real text; only the console shows '?')
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

FT = r"C:\FTTest"
LOG = os.path.join(FT, "logs")
DEALS = os.path.join(LOG, "forward", "deals.csv")
LIVE = os.path.join(LOG, "live.json")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

# friendly one-line descriptions (what it trades, in human words)
DESC = {
    "smvp": "supply/demand zones (the champion)",
    "breakout": "range breakouts",
    "macross": "moving-average crosses",
    "straddle": "session-open straddles",
    "smc": "smart-money structure",
    "london": "London-open moves",
    "squeeze": "volatility-squeeze bursts",
    "fixfade": "London-fix rebalancing fade (new)",
    "donchian": "channel breakouts (on notice until Oct 8)",
    "trendpullback": "trend pullbacks (retired Oct 1)",
    "trend": "trend-following (strongest edge)",
    "vwaprev": "VWAP reversion (new)",
    "dayopen": "server-day-open long (new)",
    "supertrend": "supertrend flips",
    "liquiditysweep": "liquidity sweeps H4 (my port)",
    "liquiditysweep-BIN": "liquidity sweeps H4 (your binary)",
    "aetherflow": "aetherflow M15",
    "aetherflow-M30": "aetherflow M30",
    "aetherflow-H4": "aetherflow H4",
    "grid": "single-side recovery grid (AUTO trend + catastrophic SL)",
    "gridclone": "faithful slipstream clone (hedged, deep ladder, no SL)",
    "gridbestrr": "recommended hybrid (AUTO single-side, server TP+SL, cap 6)",
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


def fam(stream):
    for suf in ("-EA-T", "-EA", "-T"):
        if stream.endswith(suf):
            return fam(stream[:-len(suf)])
    if stream.startswith("aetherflow"):
        return stream          # M30/H4 kept separate in this report
    return stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (UTC), default today")
    ap.add_argument("--json", default=os.path.join(LOG, "day_perf.json"))
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()
    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    per = defaultdict(lambda: {"net": 0.0, "n": 0, "wins": 0})
    with open(DEALS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["entry"] != "out" or row["time_utc"][:10] != day:
                continue
            pnl = (float(row["profit"] or 0) + float(row["commission"] or 0)
                   + float(row["swap"] or 0))
            d = per[fam(row["strategy"])]
            d["net"] += pnl
            d["n"] += 1
            d["wins"] += 1 if pnl > 0 else 0

    live = {}
    try:
        with open(LIVE, encoding="utf-8") as fh:
            live = json.load(fh)
    except (OSError, ValueError):
        pass

    winners = [(k, v) for k, v in per.items() if v["net"] > 0]
    losers = [(k, v) for k, v in per.items() if v["net"] < 0]
    winners.sort(key=lambda kv: -kv[1]["net"])
    losers.sort(key=lambda kv: kv[1]["net"])
    traded = set(per)
    quiet = sorted(set(DESC) - traded)
    total = sum(v["net"] for v in per.values())
    n_trips = sum(v["n"] for v in per.values())

    L = ["📊 Day report -- %s (UTC)" % day]
    if live:
        L.append("Balance $%s | Today %+.2f | open %s (float %+.2f)"
                 % (live.get("bal", "?"), live.get("n_day", total),
                    live.get("open", "?"), live.get("n_flt", 0.0)))
    else:
        L.append("Today: %+.2f across %d trips" % (total, n_trips))
    L.append("")
    if winners:
        L.append("✅ WINNERS")
        for k, v in winners:
            L.append("  %s %+.2f  (%d trades, %d won) -- %s"
                     % (k, v["net"], v["n"], v["wins"], DESC.get(k, "")))
    if losers:
        L.append("")
        L.append("🔻 LOSERS")
        for k, v in losers:
            L.append("  %s %+.2f  (%d trades, %d won) -- %s"
                     % (k, v["net"], v["n"], v["wins"], DESC.get(k, "")))
    if quiet:
        L.append("")
        L.append("😴 No trades today: %s" % ", ".join(quiet))
        L.append("   (normal -- these wait for their setup, nothing is broken)")
    L.append("")
    if winners and losers:
        L.append("Bottom line: %s carried the day (+%.2f), %s cost the most (%.2f). Day total %+.2f."
                 % (winners[0][0], winners[0][1]["net"],
                    losers[0][0], losers[0][1]["net"], total))
    elif winners:
        L.append("Bottom line: clean day -- %s led (+%.2f). Day total %+.2f."
                 % (winners[0][0], winners[0][1]["net"], total))
    elif losers:
        L.append("Bottom line: rough day -- %s hurt most (%.2f). Day total %+.2f."
                 % (losers[0][0], losers[0][1]["net"], total))
    else:
        L.append("Bottom line: no closed trades today. Day total 0.00.")

    msg = "\n".join(L)
    print(msg)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"day": day, "total": round(total, 2), "n": n_trips,
                       "per": {k: {"net": round(v["net"], 2), "n": v["n"],
                                   "wins": v["wins"]} for k, v in per.items()}},
                      fh, indent=1)
    if not args.no_send:
        ok = send_telegram(msg)
        print("telegram: %s" % ("sent" if ok else "SEND FAILED"))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
