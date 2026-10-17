"""Temp: export magic-300003 deals WITH position_id for exact reconstruction."""
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

ok = mt5.initialize(timeout=15000)
print("init:", ok, flush=True)
if not ok:
    raise SystemExit(1)
try:
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=60),
                                  now + timedelta(days=2)) or []
    rows = [d for d in deals if d.magic == 300003 and d.type in (0, 1)]
    print("rows:", len(rows), flush=True)
    with open("C:/FTTest/scripts/_tmp_grid300003.csv", "w") as f:
        f.write("ticket,time,position_id,type,entry,volume,price,profit,commission,swap,comment\n")
        for d in rows:
            f.write("%d,%d,%d,%d,%d,%.2f,%.3f,%.2f,%.2f,%.2f,%s\n" % (
                d.ticket, d.time, d.position_id, d.type, d.entry,
                d.volume, d.price, d.profit, d.commission, d.swap,
                (d.comment or "").replace(",", ";")))
    print("wrote", flush=True)
finally:
    mt5.shutdown()
print("done", flush=True)
