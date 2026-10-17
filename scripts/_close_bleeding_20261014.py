r"""One-shot retirement helper (2026-10-14): user authorized closing positions
at market for the removed bleeding families, then detaching their EAs.

Targets (magics): trend 940012, vwaprev 930013/940013, swing 930018/940018,
swing-m30 930019/940019, sweepabs 930020/940020. Untouched: breakout 930001,
straddle 930004/940004, smc, london, macross, fixfade, aetherflow, dayopen,
liquiditysweep, SMVP.

Actions: close open positions at market (IOC, deviation 100), delete pending
orders of the target magics. DEMO rail: refuses anything but a demo account.

Exit codes: 0 = ok (closed/cancelled or nothing found), 3 = mt5 attach failed,
2 = not demo, 4 = some action failed.
"""
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import load_env

RETIRED = (940012, 930013, 940013, 930018, 940018, 930019, 940019,
           930020, 940020)

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

    # --- cancel pendings of target magics first (SENTINEL paramname: RETIRE_PEND) ---
    orders = mt5.orders_get() or []
    mine = [o for o in orders if o.magic in RETIRED]
    pend_ok = True
    for o in mine:
        r = mt5.order_send({
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": o.ticket,
            "magic": o.magic,
            "comment": "retire cancel",
        })
        if r is None:
            print("cancel #%d magic=%d ORDER_SEND NONE (%s)"
                  % (o.ticket, o.magic, mt5.last_error()))
            pend_ok = False
        else:
            print("cancel #%d magic=%d ret=%s" % (o.ticket, o.magic, r.retcode))
            pend_ok = pend_ok and r.retcode == mt5.TRADE_RETCODE_DONE
    if not mine:
        print("no pendings on retired magics")

    # --- close positions of target magics at market ---
    poss = mt5.positions_get() or []
    mine = [p for p in poss if p.magic in RETIRED]
    if not mine:
        print("no open positions on retired magics")
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
            "price": (tick.bid if p.type == mt5.POSITION_TYPE_BUY
                      else tick.ask),
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

    # --- verify ---
    left = [p for p in (mt5.positions_get() or []) if p.magic in RETIRED]
    lorders = [o for o in (mt5.orders_get() or []) if o.magic in RETIRED]
    print("remaining on retired magics: positions=%d pendings=%d"
          % (len(left), len(lorders)))
    sys.exit(0 if (trade_ok and pend_ok and not left and not lorders) else 4)
finally:
    mt5.shutdown()
