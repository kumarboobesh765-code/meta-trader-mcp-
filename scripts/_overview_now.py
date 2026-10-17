"""Quick overview: account state from live.json + today's closed P&L per family
from deals.csv + open positions snapshot (file-based, no MT5 attach)."""
import json
import csv
import os
from datetime import datetime, timezone

LIVE = r"C:\FTTest\logs\live.json"
DEALS = r"C:\FTTest\logs\forward\deals.csv"

try:
    with open(LIVE, encoding="utf-8") as f:
        lv = json.load(f)
    print("LIVE  bal=%s eq=%s open=%s floating=%s gen=%s"
          % (lv.get("bal"), lv.get("eq"), lv.get("open"), lv.get("flt"), lv.get("gen")))
    print("      session_closed=%s today=%s" % (lv.get("closed"), lv.get("day")))
except Exception as e:
    print("live.json unreadable: %r" % e)

# today's closes per family (deals.csv time_utc is ISO; 'out' rows carry profit)
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
fam_today = {}
n_today = 0
if os.path.exists(DEALS):
    with open(DEALS, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("entry") != "out" or not (row.get("time_utc") or "").startswith(today):
                continue
            n_today += 1
            fam = row.get("strategy", "?")
            try:
                fam_today[fam] = fam_today.get(fam, 0.0) + float(row.get("profit", 0))
            except ValueError:
                pass
print("\nTODAY closes: %d | net per family:" % n_today)
for fam, v in sorted(fam_today.items(), key=lambda kv: -abs(kv[1])):
    print("  %-18s %+8.2f" % (fam, v))
print("  %-18s %+8.2f" % ("TOTAL", sum(fam_today.values())))
