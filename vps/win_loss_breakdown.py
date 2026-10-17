"""Read-only win/loss breakdown for the grid strategies. Never trades."""
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

NAMES = {
    930021: "GridRecovery (930021)",
    930022: "Bare BUY grid (930022)",
    930023: "GridBestRR v1.01 (930023)",
}

if not mt5.initialize(timeout=15000):
    raise SystemExit("INIT_FAIL %s" % (mt5.last_error(),))
try:
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(datetime(2020, 1, 1, tzinfo=timezone.utc),
                                  now + timedelta(minutes=5)) or []
    closes = [d for d in deals if d.magic in NAMES and d.type in (0, 1) and d.entry == 1]
    for m, name in NAMES.items():
        c = [d for d in closes if d.magic == m]
        if not c:
            print("%s: no closed trades" % name)
            continue
        net = [d.profit + d.commission + d.swap for d in c]
        wins = [x for x in net if x > 0]
        losses = [x for x in net if x <= 0]
        gross_w = sum(wins)
        gross_l = sum(losses)
        comm = sum(d.commission for d in c)
        swap = sum(d.swap for d in c)
        print(name)
        print("  trades=%d wins=%d losses=%d" % (len(net), len(wins), len(losses)))
        print("  avg win=%+.2f  avg loss=%+.2f  largest loss=%+.2f" % (
            (gross_w / len(wins)) if wins else 0.0,
            (gross_l / len(losses)) if losses else 0.0,
            min(net)))
        print("  total from wins=%+.2f  total from losses=%+.2f  net=%+.2f" % (
            gross_w, gross_l, gross_w + gross_l))
        print("  commission=%+.2f  swap=%+.2f" % (comm, swap))
finally:
    mt5.shutdown()
