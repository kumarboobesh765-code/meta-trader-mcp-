"""Probe the PATCHED supertrend_dir() in backtest_new_candidates.py (no MT5:
MetaTrader5 stubbed). Must keep the module contract (+1 = uptrend) while
matching the proven st_dir_pine() exactly (inverted)."""
import sys
import types
import importlib.util

mt5_stub = types.ModuleType("MetaTrader5")
mt5_stub.initialize = lambda *a, **k: False
for _n, _v in (("TIMEFRAME_M15", 15), ("TIMEFRAME_M30", 30), ("TIMEFRAME_H1", 16385),
               ("ACCOUNT_TRADE_MODE_DEMO", 0), ("DEAL_TYPE_BUY", 0),
               ("DEAL_TYPE_SELL", 1), ("DEAL_ENTRY_IN", 0), ("DEAL_ENTRY_OUT", 1)):
    setattr(mt5_stub, _n, _v)
sys.modules["MetaTrader5"] = mt5_stub

sys.path.insert(0, "scripts")
import backtest_new_candidates as bnc
import backtest_supertrend as bts


def mk_bars(closes):
    return [{"time": 1000 + i * 3600, "open": c, "high": c + 1.0,
             "low": c - 1.0, "close": c} for i, c in enumerate(closes)]


def flips(d):
    return [i for i in range(1, len(d)) if d[i] != d[i - 1]]


def pct(seq, v):
    return 100.0 * sum(1 for x in seq if x == v) / max(1, len(seq))


fails = []

# 1) exact parity with the proven port (inverted contract), several params
import random
random.seed(7)
px = 4000.0
bars = []
for i in range(1200):
    px += random.uniform(-14.0, 14.0)
    bars.append({"time": 1000 + i * 3600, "open": px, "high": px + 0.7,
                 "low": px - 0.7, "close": px})
for period, factor in ((10, 3.0), (5, 2.0), (7, 1.5)):
    a = bnc.supertrend_dir(bars, period, factor)
    b = bts.st_dir_pine(bars, period, factor)
    mism = sum(1 for x, y in zip(a, b) if x != -y)
    print("parity (%d,%.1f): mismatches=%d/%d" % (period, factor, mism, len(a)))
    if mism:
        fails.append("parity (%d,%.1f) mismatches=%d" % (period, factor, mism))

# 2) contracts on synthetic shapes
dn = bnc.supertrend_dir(mk_bars([5000 - 2.0 * i for i in range(500)]), 10, 3.0)
print("downtrend: down%%=%.1f (want ~100)" % pct(dn, -1))
if pct(dn, -1) < 95:
    fails.append("downtrend not down")

up = bnc.supertrend_dir(mk_bars([4000 + 2.0 * i for i in range(500)]), 10, 3.0)
print("uptrend:   up%%=%.1f (want ~100)" % pct(up, 1))
if pct(up, 1) < 95:
    fails.append("uptrend not up")

sq, p = [], 4000.0
for _ in range(6):
    for _ in range(60):
        p += 3.0
        sq.append(p)
    for _ in range(60):
        p -= 3.0
        sq.append(p)
d = bnc.supertrend_dir(mk_bars(sq), 10, 3.0)
kinds = set(d[i] for i in flips(d))
print("square: flips=%d kinds=%s" % (len(flips(d)), kinds))
if len(flips(d)) < 4 or kinds != {-1, 1}:
    fails.append("square wave wrong")

v = [4000 + 2.0 * i for i in range(250)] + [4500 - 2.0 * i for i in range(1, 251)]
d = bnc.supertrend_dir(mk_bars(v), 10, 3.0)
print("V-shape: flips=%d end=%d (want 2, end -1)" % (len(flips(d)), d[-1]))
if len(flips(d)) != 2 or d[-1] != -1:
    fails.append("V-shape wrong")

print("\nRESULT: %s" % ("FAIL %s" % fails if fails else "ALL PROBES PASS"))
sys.exit(1 if fails else 0)
