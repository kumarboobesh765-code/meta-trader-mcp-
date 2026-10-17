r"""Read-only identity probe for a NEW login on the MT5 terminal.
Prints login/server/mode/balance only. NEVER sends orders (like all rig
probes) and does NOT refuse non-demo -- that is exactly what we want to see.
"""
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import load_env

load_env()
ok = False
for attempt in range(4):
    if mt5.initialize():
        ok = True
        break
    print("attach attempt %d failed: %s" % (attempt + 1, mt5.last_error()))
    mt5.shutdown()
    time.sleep(8)
if not ok:
    sys.exit(3)

try:
    acc = mt5.account_info()
    if acc is None:
        print("account_info None: %s" % (mt5.last_error(),))
        sys.exit(2)
    MODE = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
    print("login=%s server=%s mode=%s currency=%s" % (
        acc.login, acc.server, MODE.get(acc.trade_mode, str(acc.trade_mode)),
        acc.currency))
    print("balance=%.2f equity=%.2f margin=%.2f free=%.2f" % (
        acc.balance, acc.equity, acc.margin, acc.margin_free))
    print("leverage=1:%s  margin_so_call=%s  margin_so_so=%s" % (
        acc.leverage, acc.margin_so_call, acc.margin_so_so))
    poss = mt5.positions_get() or []
    print("open positions: %d" % len(poss))
    for p in poss:
        print("  #%d magic=%d %s vol=%s pnl=%+.2f" % (
            p.ticket, p.magic, p.symbol, p.volume, p.profit))
    ords = mt5.orders_get() or []
    print("pending orders: %d" % len(ords))
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick:
        print("XAUUSD bid=%.2f ask=%.2f" % (tick.bid, tick.ask))
    else:
        print("no XAUUSD tick -- market feed may be offline")
finally:
    mt5.shutdown()
