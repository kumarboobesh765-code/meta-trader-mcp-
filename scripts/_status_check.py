"""Read-only status report for the forward-test account. No orders, no state."""
import sys
from datetime import datetime, timedelta

import MetaTrader5 as mt5

MAGICS = {
    910001: "breakout", 910002: "meanrev", 910003: "macross", 910004: "straddle",
    920001: "breakout-T", 920002: "meanrev-T", 920003: "macross-T", 920004: "straddle-T",
    930001: "breakout-EA", 930002: "meanrev-EA", 930003: "macross-EA", 930004: "straddle-EA", 930005: "smc-EA",
    940001: "breakout-EA-T", 940002: "meanrev-EA-T", 940003: "macross-EA-T", 940004: "straddle-EA-T", 940005: "smc-EA-T",
    910005: "smc", 910006: "london", 910007: "squeeze",
    920005: "smc-T", 920006: "london-T", 920007: "squeeze-T",
    930006: "london-EA", 930007: "squeeze-EA",
    940006: "london-EA-T", 940007: "squeeze-EA-T",
}

if not mt5.initialize():
    print("INIT FAILED:", mt5.last_error())
    sys.exit(1)

try:
    ai = mt5.account_info()
    if ai is None:
        print("account_info unavailable:", mt5.last_error())
        sys.exit(1)
    print("ACCOUNT", ai.login, ai.server, ai.currency)
    print("BALANCE %.2f EQUITY %.2f PROFIT %.2f MARGIN %.2f FREE %.2f" % (
        ai.balance, ai.equity, ai.profit, ai.margin, ai.margin_free))

    tick = mt5.symbol_info_tick("XAUUSD")
    if tick:
        print("XAUUSD bid=%.2f ask=%.2f" % (tick.bid, tick.ask))

    positions = mt5.positions_get() or []
    print("OPEN_POSITIONS", len(positions))
    for p in positions:
        print("  POS ticket=%d %s %s vol=%.2f open=%.2f sl=%.2f tp=%.2f profit=%.2f magic=%d %s" % (
            p.ticket, "BUY " if p.type == 0 else "SELL", p.symbol, p.volume,
            p.price_open, p.sl, p.tp, p.profit, p.magic, MAGICS.get(p.magic, "?")))

    otypes = {2: "BUY LIMIT ", 3: "SELL LIMIT", 4: "BUY STOP ", 5: "SELL STOP"}
    orders = mt5.orders_get() or []
    print("PENDING_ORDERS", len(orders))
    for o in orders:
        print("  ORD ticket=%d %s %s price=%.2f vol=%.2f magic=%d %s" % (
            o.ticket, otypes.get(o.type, "type%d" % o.type), o.symbol, o.price_open,
            o.volume_current, o.magic, MAGICS.get(o.magic, "?")))

    now = datetime.now()
    # Broker stamps deals in server time (UTC+2/3), which lands "in the future"
    # vs UTC-converted local now -- extend the window end so recent deals count.
    deals = mt5.history_deals_get(now - timedelta(days=30), now + timedelta(days=2)) or []
    closed = [d for d in deals if d.entry == 1]  # DEAL_ENTRY_OUT
    per = {}
    for d in closed:
        k = MAGICS.get(d.magic, "other(%d)" % d.magic)
        t = per.setdefault(k, [0, 0.0])
        t[0] += 1
        t[1] += d.profit + d.commission + d.swap
    print("CLOSED_30D_ALL", len(closed))
    for k in sorted(per):
        n, pl = per[k]
        print("  %-16s trades=%-5d net=%9.2f" % (k, n, pl))
    ours = sum(v[1] for k, v in per.items() if not k.startswith("other("))
    tot = sum(v[1] for v in per.values())
    print("TOTAL_30D_NET %.2f (fttest %.2f, rest %.2f)" % (tot, ours, tot - ours))
finally:
    mt5.shutdown()
