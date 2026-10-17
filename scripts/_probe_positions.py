"""Where did the 2026-09-25 04:21 UTC straddle longs go? Query deals by position id."""
import MetaTrader5 as mt5

POS_IDS = [552704196, 552704197, 552704563, 552704714]

print("probe2: start", flush=True)
ok = mt5.initialize(timeout=15000)
print("probe2: init =", ok, flush=True)
if ok:
    for pid in POS_IDS:
        ds = mt5.history_deals_get(position=pid) or ()
        print("position", pid, "deals:", len(ds), flush=True)
        for d in ds:
            print("   deal ticket=%d entry=%d type=%d vol=%.2f price=%.2f profit=%.2f magic=%d comment=%r time=%s" % (
                d.ticket, d.entry, d.type, d.volume, d.price, d.profit, d.magic, d.comment, str(d.time)), flush=True)
    mt5.shutdown()
print("probe2: done", flush=True)
