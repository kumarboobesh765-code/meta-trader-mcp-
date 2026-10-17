"""Full entry/exit chain for the two anomalous Sep-28 magic-0 positions.

pids 2049574657 and 2049581094 closed at 4197.61 / 4196.77 for +178.48 /
+182.04 on 0.01 lots. Find their entry deals regardless of magic so we can see
the actual price move, and check the account's own price scale that day.
"""
import datetime as dt
import time

import MetaTrader5 as mt5

TARGETS = {2049574657, 2049581094}


def ts(t):
    return dt.datetime.fromtimestamp(int(t), dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

alld = mt5.history_deals_get(0, int(time.time()))
print("total deals in history: %d" % len(alld))

print("\n=== chain for the two Sep-28 positions (any magic) ===")
for d in alld:
    if d.position_id in TARGETS:
        kind = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}.get(d.entry, str(d.entry))
        print("  %s  pid=%d %-6s magic=%d %-6s %-4s vol=%.2f price=%.2f pnl=%+9.2f"
              % (ts(d.time), d.position_id, kind, d.magic, d.symbol,
                 "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                 d.volume, d.price, d.profit))

print("\n=== every XAUUSD deal on 09-28 between 00:00 and 08:00 (magic any) ===")
for d in alld:
    if d.symbol != "XAUUSD" or not d.time:
        continue
    stamp = ts(d.time)
    if not stamp.startswith("2026-09-28") or stamp[11:13] > "07":
        continue
    kind = {0: "IN", 1: "OUT"}.get(d.entry, str(d.entry))
    print("  %s  pid=%-11d magic=%-9d %-3s %-4s vol=%.2f price=%9.2f pnl=%+9.2f"
          % (stamp, d.position_id, d.magic, kind,
             "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
             d.volume, d.price, d.profit))

print("\n=== deals with |pnl| > 100 anywhere in history (the fat tail) ===")
for d in alld:
    if abs(d.profit) > 100:
        print("  %s  pid=%-11d magic=%-9d %-7s %-4s vol=%.2f price=%9.2f pnl=%+9.2f"
              % (ts(d.time), d.position_id, d.magic, d.symbol,
                 "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                 d.volume, d.price, d.profit))

mt5.shutdown()