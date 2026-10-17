r"""One-off XAU-only cleanup: close every open position and cancel every
pending order whose symbol is NOT XAUUSD. XAUUSD positions are never touched.
Safety: demo accounts only; retries each close once; prints a full audit.

Run ON THE VPS: python C:/FTTest/scripts/_close_fx_once.py
"""
import sys

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from forward_test import load_env

DEVIATION = 100


def filling_for(sym):
    info = mt5.symbol_info(sym)
    fm = info.filling_mode if info else 0
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def close_position(p):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return False, "no tick"
    is_buy = (p.type == mt5.POSITION_TYPE_BUY)
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": p.ticket,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if is_buy else tick.ask,
        "deviation": DEVIATION,
        "magic": p.magic,
        "comment": "xauonly-cleanup",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_for(p.symbol),
    }
    r = mt5.order_send(req)
    if r is None:
        return False, "order_send None (ret=%s)" % (mt5.last_error(),)
    if r.retcode == mt5.TRADE_RETCODE_DONE:
        return True, "closed @ %.5f" % r.price
    return False, "retcode=%d" % r.retcode


def cancel_pending(o):
    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
    r = mt5.order_send(req)
    if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
        return True, "cancelled"
    return False, "retcode=%d" % (r.retcode if r else -1)


def main():
    load_env()
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only (account=%s)" % (acc and acc.login))
        mt5.shutdown()
        return 1
    print("account %s %s (demo ok)" % (acc.login, acc.server))

    # PENDINGS FIRST: orphan FX stop orders can still FILL into new
    # positions even though MultiEA is gone, so kill them before closing.
    orders = mt5.orders_get() or []
    fx_pend = [o for o in orders if o.symbol != "XAUUSD"]
    print("pendings: %d total -> %d non-XAU to cancel" % (len(orders), len(fx_pend)))
    for o in fx_pend:
        ok, msg = cancel_pending(o)
        print("  %s %-8s #%d type=%d -> %s"
              % ("OK  " if ok else "FAIL", o.symbol, o.ticket, o.type, msg))

    poss = mt5.positions_get() or []
    fx = [p for p in poss if p.symbol != "XAUUSD"]
    gold = [p for p in poss if p.symbol == "XAUUSD"]
    fl = sum(p.profit + p.swap for p in fx)
    print("open: %d total -> %d non-XAU to close (floating %+.2f), "
          "%d XAU keep" % (len(poss), len(fx), fl, len(gold)))

    closed_n = 0
    realized = 0.0
    for p in sorted(fx, key=lambda p: p.symbol):
        ok, msg = close_position(p)
        if not ok:                       # one retry
            ok, msg = close_position(p)
        tag = "OK  " if ok else "FAIL"
        print("  %s %-8s magic=%-8d %.2f lots pnl=%+.2f -> %s"
              % (tag, p.symbol, p.magic, p.volume, p.profit + p.swap, msg))
        if ok:
            closed_n += 1
            realized += p.profit + p.swap

    after = mt5.positions_get() or []
    left_fx = [p for p in after if p.symbol != "XAUUSD"]
    print("RESULT: closed %d/%d positions, realized %+.2f, cancelled %d pendings; "
          "remaining open=%d (non-XAU left=%d), XAU kept=%d"
          % (closed_n, len(fx), realized,
             sum(1 for o in fx_pend if o), len(after), len(left_fx),
             sum(1 for p in after if p.symbol == "XAUUSD")))
    mt5.shutdown()
    return 0 if not left_fx else 1


if __name__ == "__main__":
    sys.exit(main())
