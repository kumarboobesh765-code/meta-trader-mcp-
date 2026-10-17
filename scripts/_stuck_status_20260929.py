"""Status check: are the stuck sells closed? What did the close attempt do?"""
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

TICKETS = [2103956425, 2103956435, 2104175793]

mt5.initialize()
op = {p.ticket: p for p in (mt5.positions_get() or [])}
for t in TICKETS:
    if t in op:
        p = op[t]
        print(f"#{t} STILL OPEN sl={p.sl} cur={p.price_current} pnl={p.profit:+.2f}")
    else:
        print(f"#{t} closed")
acc = mt5.account_info()
print(f"bal={acc.balance:.2f} eq={acc.equity:.2f}")
now = datetime.now(timezone.utc)
d = mt5.history_deals_get(now - timedelta(hours=3), now + timedelta(hours=1)) or []
outs = [x for x in d if x.position_id in TICKETS and x.entry == 1]
for x in outs:
    print(f"deal pos={x.position_id} price={x.price} pnl={x.profit:+.2f} reason={x.reason} "
          f"comment={x.comment!r} at {datetime.fromtimestamp(x.time, timezone.utc):%H:%M:%S}Z")
if not outs:
    print("(no closing deals yet in last 3h)")
mt5.shutdown()
