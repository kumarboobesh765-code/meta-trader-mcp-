"""Check the profile pair 2107542405/11 state + recent close deals for them."""
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

PAIR = [2107542405, 2107542411]
mt5.initialize()
op = {p.ticket: p for p in (mt5.positions_get() or [])}
for t in PAIR:
    if t in op:
        p = op[t]
        side = "BUY" if p.type == 0 else "SELL"
        print(f"#{t} magic={p.magic} {side} sl={p.sl} tp={p.tp} cur={p.price_current} pnl={p.profit:+.2f}")
    else:
        print(f"#{t} gone (closed)")
now = datetime.now(timezone.utc)
d = mt5.history_deals_get(now - timedelta(hours=2), now + timedelta(hours=1)) or []
reasons = {1: "SL", 2: "TP", 3: "EA/manual", 4: "MOBILE"}
for x in d:
    if x.position_id in PAIR and x.entry == 1:
        print(f"deal pos={x.position_id} price={x.price} pnl={x.profit:+.2f} "
              f"reason={reasons.get(x.reason, x.reason)} comment={x.comment!r} "
              f"at {datetime.fromtimestamp(x.time, timezone.utc):%H:%M:%S}Z")
mt5.shutdown()
