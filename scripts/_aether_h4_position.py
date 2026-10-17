"""Ad-hoc: state of the stale aetherflow-H4 position (both twins).

Decision support for closing or holding the 29h short opened at 4145 while
price ran to ~4185. Reports: age in bars, distance to SL/TP in dollars at
0.01 lot, the UT signal state now, and what a 12-bar cap would have done.
Runs ON THE VPS. Read-only.
"""
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import load_env

MAGICS = (950003, 960003)


def main():
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    tick = mt5.symbol_info_tick("XAUUSD")
    price = tick.bid if tick else 0.0
    print("bid=%.2f  bal=%.2f eq=%.2f  now=%s"
          % (price, acc.balance, acc.equity,
             datetime.now(timezone.utc).strftime("%m-%d %H:%M UTC")))
    if si:
        print("ATR-ish: point=%.2f  stops_level=%d freeze_level=%d"
              % (si.point, si.trade_stops_level, si.trade_freeze_level))

    poss = [p for p in (mt5.positions_get() or []) if p.magic in MAGICS]
    if not poss:
        print("no aetherflow-H4 positions open")
        mt5.shutdown()
        return 0
    for p in poss:
        opened = datetime.fromtimestamp(p.time, tz=timezone.utc)
        age_h = (time.time() - p.time) / 3600.0
        age_bars = age_h / 4.0            # H4 = 4h per bar
        # dollars per 1.00 price move at 0.01 lot on XAUUSD: DPU
        dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01 \
            if si else 1.0
        to_sl = (p.sl - price) * dpu if p.type == mt5.POSITION_TYPE_SELL \
            else (price - p.sl) * dpu
        to_tp = (price - p.tp) * dpu if p.type == mt5.POSITION_TYPE_SELL \
            else (p.tp - price) * dpu
        print("\nmagic %d %s @ %.2f  sl=%.2f tp=%.2f  age=%.1fh (%.1f H4 bars)"
              % (p.magic, "SELL" if p.type == mt5.POSITION_TYPE_SELL else "BUY",
                 p.price_open, p.sl, p.tp, age_h, age_bars))
        print("  opened %s | floating %+.2f" % (opened.strftime("%m-%d %H:%M"),
                                                 p.profit + p.swap))
        print("  price must rise %.2f to hit SL (%+.2f more) OR fall %.2f to "
              "hit TP (%+.2f gain)" % (p.sl - price, -to_sl,
                                       price - p.tp, to_tp))
        print("  cap check: 12 bars = 48h -> time stop fires in %.1fh"
              % max(0.0, 48.0 - age_h))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
