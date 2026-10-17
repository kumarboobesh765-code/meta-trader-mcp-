"""One-shot retirement helper (2026-09-30): close any open positions held by
the retired profile-EA twins (magics 930008 / 940008). Meanrev (930002/940002)
is checked too but expected flat. DEMO rail: refuses anything but demo.

Exit codes: 0 = ok (closed or nothing open), 3 = mt5 attach failed (-6 case).
"""
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import load_env

RETIRED = (930008, 940008, 930002, 940002)

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
    print("ATTACH_FAILED")
    sys.exit(3)

try:
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        sys.exit(2)
    poss = mt5.positions_get() or []
    mine = [p for p in poss if p.magic in RETIRED]
    if not mine:
        print("no open positions on retired magics -- nothing to do")
        sys.exit(0)
    trade_ok = True
    for p in mine:
        tick = mt5.symbol_info_tick(p.symbol)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": (mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY
                     else mt5.ORDER_TYPE_BUY),
            "price": (tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask),
            "deviation": 100,
            "magic": p.magic,
            "comment": "retire close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r is None:
            print("close #%d magic=%d ORDER_SEND NONE (%s)"
                  % (p.ticket, p.magic, mt5.last_error()))
            trade_ok = False
            continue
        print("close #%d magic=%d ret=%s (%s)"
              % (p.ticket, p.magic, r.retcode, r.comment))
        trade_ok = trade_ok and r.retcode == mt5.TRADE_RETCODE_DONE
    sys.exit(0 if trade_ok else 4)
finally:
    mt5.shutdown()
