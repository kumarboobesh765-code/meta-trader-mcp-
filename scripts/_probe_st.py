"""Sanity-probe supertrend_dir from backtest_new_candidates on real H1/M15 bars."""
import sys
sys.path.insert(0, "C:/FTTest/scripts")
from backtest_new_candidates import supertrend_dir
from forward_test import closed_bars, load_env
import MetaTrader5 as mt5

load_env()
for attempt in range(5):
    if mt5.initialize():
        break
    mt5.shutdown()
    import time; time.sleep(5)

bars = closed_bars("XAUUSD", "H1", 2760)
mt5.shutdown()
print("bars: %d  first %s  last %s" % (len(bars), bars[0]["time"], bars[-1]["time"]))
print("sample bar keys:", list(bars[100].keys()))
print("sample bar:", bars[100])

for period, factor in ((10, 3.0), (10, 2.0), (10, 1.5), (7, 1.5)):
    d = supertrend_dir(bars, period, factor)
    ups = sum(1 for x in d if x == 1)
    flips = [i for i in range(1, len(d)) if d[i] != d[i - 1]]
    print("\n(%d, %.1f): up_bars=%d down_bars=%d flips=%d"
          % (period, factor, ups, len(d) - ups, len(flips)))
    if flips:
        i = flips[0]
        print("  first flip at bar %d time %s close %.2f -> dir %d"
              % (i, bars[i]["time"], bars[i]["close"], d[i]))
        print("  last 3 flips at:", [(f, bars[f]["time"]) for f in flips[-3:]])
