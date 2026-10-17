"""Diagnose magic=0 deals + check Sep 26-27 account flatness."""
import csv
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

LOG = r"C:\FTTest\logs"

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

deals = mt5.history_deals_get(datetime(2026, 9, 20, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1))

print("=== deals with magic==0 (non-balance) ===")
pos_ids = set()
for d in deals:
    if d.magic == 0 and d.type != mt5.DEAL_TYPE_BALANCE:
        t = datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat()
        print(f"  ticket={d.ticket} pos={d.position_id} {t} {d.symbol} "
              f"type={d.type} entry={d.entry} vol={d.volume} price={d.price} "
              f"profit={d.profit:+.2f} comm={d.commission:+.2f} swap={d.swap:+.2f} reason={d.reason}")
        pos_ids.add(d.position_id)

print()
print("=== full deal trail of those positions (all deals sharing position_id) ===")
for d in deals:
    if d.position_id in pos_ids:
        t = datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat()
        print(f"  pos={d.position_id} ticket={d.ticket} {t} {d.symbol} entry={d.entry} "
              f"vol={d.volume} price={d.price} magic={d.magic} profit={d.profit:+.2f} "
              f"comm={d.commission:+.2f} swap={d.swap:+.2f} reason={d.reason}")

print()
print("=== equity.csv: balance at key windows (Sep 26 -> 28) ===")
with open(LOG + r"\forward\equity.csv", newline='', encoding='utf-8') as f:
    rows = list(csv.reader(f))
hdr = rows[0]
bal_i = hdr.index('balance')
seen = {}
for r in rows[1:]:
    day = r[0][:13]  # hourly buckets
    seen[day] = float(r[bal_i])
days = sorted(seen)
# print first snapshot of each day + a few key hours
shown = set()
for day in days:
    d2 = day[:10]
    if d2 not in shown or day.endswith('T23'):
        print(f"  {day}:00  balance={seen[day]:.2f}")
        shown.add(d2)
mt5.shutdown()
