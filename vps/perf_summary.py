"""Read-only performance summary for the running grid strategies.
Never trades. Prints plain numbers per magic."""
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from collections import defaultdict

NAMES = {
    930021: "GridRecovery (930021)",
    930022: "Bare BUY grid (930022)",
    930023: "GridBestRR v1.01 (930023)",
}
SINCE = datetime(2026, 10, 15, 4, 34, tzinfo=timezone.utc)  # 10:34 VPS local (UTC+5:30 -> 05:04 UTC; see note)

if not mt5.initialize(timeout=15000):
    raise SystemExit("INIT_FAIL %s" % (mt5.last_error(),))
try:
    a = mt5.account_info()
    print("ACCOUNT %s balance=%.2f equity=%.2f" % (a.login, a.balance, a.equity))
    pos = [p for p in (mt5.positions_get() or []) if p.magic in NAMES]
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(datetime(2020, 1, 1, tzinfo=timezone.utc),
                                  now + timedelta(minutes=5)) or []
    closes = [d for d in deals if d.magic in NAMES and d.type in (0, 1) and d.entry == 1]
    for m, name in NAMES.items():
        op = [p for p in pos if p.magic == m]
        flt = sum(p.profit + p.swap for p in op)
        c_all = [d for d in closes if d.magic == m]
        net_all = sum(d.profit + d.commission + d.swap for d in c_all)
        wins = sum(1 for d in c_all if d.profit + d.commission + d.swap > 0)
        print("%s" % name)
        print("  open trades=%d  floating=%+.2f" % (len(op), flt))
        print("  closed trades=%d  net=%+.2f  win rate=%s" % (
            len(c_all), net_all,
            ("%.0f%%" % (100.0 * wins / len(c_all))) if c_all else "n/a"))
finally:
    mt5.shutdown()
