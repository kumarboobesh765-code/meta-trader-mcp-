import datetime
import sys

import MetaTrader5 as mt5

if not mt5.initialize():
    print("mt5 init failed:", mt5.last_error())
    sys.exit(1)

t = mt5.symbol_info_tick("XAUUSD")
now = datetime.datetime.now().timestamp()
print("tick_time", int(t.time), "local_now", int(now),
      "offset_h", round((t.time - now) / 3600.0, 3))

for tf, n in ((mt5.TIMEFRAME_M5, 60000), (mt5.TIMEFRAME_M5, 58000),
              (mt5.TIMEFRAME_H1, 5600)):
    r = mt5.copy_rates_from_pos("XAUUSD", tf, 1, n)
    print("tf", int(tf), "requested", n, "got",
          None if r is None else len(r))

# depth sanity: first/last bar time of the big M5 fetch
r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 1, 58000)
if r is not None and len(r):
    print("first", int(r[0]["time"]),
          datetime.datetime.utcfromtimestamp(int(r[0]["time"])),
          "last", int(r[-1]["time"]),
          datetime.datetime.utcfromtimestamp(int(r[-1]["time"])))
    # per-UTC-hour tick volume profile (cross-check of epoch frame)
    hrs = {}
    for row in r:
        h = (int(row["time"]) % 86400) // 3600
        hrs[h] = hrs.get(h, 0) + int(row["tick_volume"])
    top = sorted(hrs.items(), key=lambda kv: -kv[1])[:6]
    print("top server-hours by tick vol (server-wall):", top)

mt5.shutdown()
