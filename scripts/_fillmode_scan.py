"""Ad-hoc: which filling mode does the broker accept for this XAUUSD close?

The close returned 10030 Unsupported filling mode for both the default and
explicit RETURN. This prints the ORDER_FILLING_* constants this build uses,
then order_check (validates WITHOUT sending) a set of candidate filling
values against the stale aetherflow-H4 position to find the accepted one.

Runs ON THE VPS. Sends NO orders.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import load_env

MAGICS = (950003, 960003)


def main():
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    print("constants: FOK=%d IOC=%d RETURN=%d"
          % (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC,
             mt5.ORDER_FILLING_RETURN))
    si = mt5.symbol_info("XAUUSD")
    print("symbol filling_mode=%d expiration_mode=%d"
          % (si.filling_mode, si.expiration_mode))
    poss = [p for p in (mt5.positions_get() or []) if p.magic in MAGICS]
    if not poss:
        print("no aetherflow-H4 position to probe against")
        mt5.shutdown()
        return 0
    p = poss[0]
    tick = mt5.symbol_info_tick(p.symbol)
    print("probing ticket %d %s @ %.2f (bid %.2f)"
          % (p.ticket,
             "SELL" if p.type == mt5.POSITION_TYPE_SELL else "BUY",
             p.price_open, tick.bid if tick else 0.0))
    close_type = (mt5.ORDER_TYPE_BUY if p.type == mt5.POSITION_TYPE_SELL
                  else mt5.ORDER_TYPE_SELL)
    for label, fill in (("omitted", None),
                        ("FOK", mt5.ORDER_FILLING_FOK),
                        ("IOC", mt5.ORDER_FILLING_IOC),
                        ("RETURN", mt5.ORDER_FILLING_RETURN),
                        ("raw2", 2), ("raw3", 3), ("raw4", 4),
                        ("raw6", 6), ("raw7", 7)):
        req = {"symbol": p.symbol, "action": mt5.TRADE_ACTION_DEAL,
               "position": p.ticket, "volume": p.volume, "type": close_type,
               "deviation": 50, "magic": p.magic, "comment": "fillprobe"}
        if fill is not None:
            req["type_filling"] = fill
        try:
            chk = mt5.order_check(req)
        except Exception as e:                      # noqa: BLE001
            print("  %-7s EXC %r" % (label, e))
            continue
        print("  %-7s retcode=%-6s %s" % (label, chk.retcode, chk.comment))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
