"""Who are the unmapped magic=0 deals?  They are +$383 on 4 trips with a
100% win rate and PF=inf, which is 75% of the rig's entire net. magic 0 means
"no magic set" -- so either the user traded by hand, or an EA placed orders
without tagging them. Print symbol/comment/times so the source is obvious."""
import datetime as dt
import os
import time
from collections import defaultdict

import MetaTrader5 as mt5


def ts(t):
    """Format an epoch stamp. The VPS MetaTrader5 build has no
    time_to_string(), so do it ourselves."""
    return dt.datetime.utcfromtimestamp(int(t)).strftime("%Y-%m-%d %H:%M:%S")

if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

rows = []
for d in mt5.history_deals_get(0, int(time.time())):
    if d.magic == 0 and d.entry == mt5.DEAL_ENTRY_OUT:
        rows.append(d)

rows.sort(key=lambda d: d.time)
print("magic-0 OUT deals: %d" % len(rows))
tot = 0.0
for d in rows:
    pnl = d.profit + d.commission + d.swap
    tot += pnl
    print("  %s  %-8s %-5s vol=%.2f  %+9.2f  comment=%r"
          % (ts(d.time),
             d.symbol, "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
             d.volume, pnl, d.comment))
print("TOTAL magic-0 net: %+.2f" % tot)

# which tickets, and what symbol/time did they open?
if rows:
    ticks = set()
    for d in rows:
        ticks.add(d.position_id)
    print("\nposition_ids: %s" % sorted(ticks))
mt5.shutdown()