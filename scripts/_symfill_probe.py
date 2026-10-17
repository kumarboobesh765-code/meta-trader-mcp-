"""Ad-hoc: find a working filling mode for closing aetherflow-H4 on XAUUSD.

order_send returned 10030 (Unsupported filling mode) with no type_filling.
Prints the symbol's allowed filling modes and current hedge/account mode so
the close can be retried with an explicit type_filling.
Runs ON THE VPS. Read-only (no orders).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import load_env

NAMES = {mt5.ORDER_FILLING_FOK: "FOK", mt5.ORDER_FILLING_IOC: "IOC",
         mt5.ORDER_FILLING_RETURN: "RETURN"}


def main():
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    print("account trade_mode=%d (0=disabled 1=longonly 2=shortonly 3=both)"
          % (acc.trade_mode if acc else -1))
    for sym in ("XAUUSD",):
        si = mt5.symbol_info(sym)
        if si is None:
            print("%s unavailable" % sym)
            continue
        print("%s: filling_mode=%d expiration_mode=%d trade_mode=%d"
              % (sym, si.filling_mode, si.expiration_mode, si.trade_mode))
        allowed = si.filling_mode & 0x0F
        bits = [NAMES.get(1 << i, str(1 << i)) for i in range(4)
                if allowed & (1 << i)]
        print("  allowed filling bits: %s (mask=%d)"
              % (", ".join(bits) if bits else "none", allowed))
        # live validation WITHOUT sending: order_check each candidate filling
        tick = mt5.symbol_info_tick(sym)
        p = [q for q in (mt5.positions_get() or []) if q.symbol == sym]
        if tick and p:
            for bit in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC):
                if not (allowed & bit):
                    continue
                chk = mt5.order_check({
                    "symbol": sym,
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": p[0].ticket,
                    "volume": p[0].volume,
                    "type": mt5.ORDER_TYPE_BUY
                    if p[0].type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL,
                    "deviation": 50,
                    "type_filling": bit,
                    "magic": p[0].magic,
                    "comment": "fillprobe"})
                print("  order_check %s: retcode=%s (%s) margin=%.2f"
                      % (NAMES.get(bit, bit), chk.retcode, chk.comment,
                         getattr(chk, "margin", 0.0)))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
