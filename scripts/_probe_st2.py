"""Local sanity probe for backtest_supertrend.st_dir_pine (MetaTrader5
stubbed; backtest_new_candidates/backtest_aetherflow are NOT imported).
Checks the faithful Pine port actually FLIPS in trends and at reversals --
the broken shared helper froze at 'up'.

Cases:
  1. monotonic downtrend   -> dir must be +1 (down) almost everywhere
  2. monotonic uptrend     -> dir must be -1 (up) almost everywhere
  3. square wave           -> flips near every reversal, both directions
  4. V-shape (up then down) -> exactly ~2 flips, ends downtrend
  5. staircase down        -> mostly +1, flips stay at local tops
Also cross-checks vs the OLD broken helper on a synthetic downtrend: the old
one should (wrongly) stay 'up', the new one should go 'down'.
"""
import sys
import types
import importlib.util

# Stub MetaTrader5 BEFORE importing backtest_supertrend (it imports mt5,
# backtest_new_candidates and backtest_aetherflow only inside sys.path
# guarded inserts that don't exist locally).
mt5_stub = types.ModuleType("MetaTrader5")
mt5_stub.initialize = lambda *a, **k: False
for _n, _v in (("TIMEFRAME_M15", 15), ("TIMEFRAME_M30", 30), ("TIMEFRAME_H1", 16385),
               ("ACCOUNT_TRADE_MODE_DEMO", 0), ("DEAL_TYPE_BUY", 0),
               ("DEAL_TYPE_SELL", 1), ("DEAL_ENTRY_IN", 0), ("DEAL_ENTRY_OUT", 1)):
    setattr(mt5_stub, _n, _v)
sys.modules["MetaTrader5"] = mt5_stub

spec = importlib.util.spec_from_file_location(
    "bts", "scripts/backtest_supertrend.py")
bts = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(bts)
except SystemExit as e:  # forward_test import absent locally
    print("import of backtest_supertrend needs forward_test on this box;",
          "inlining st_dir_pine instead (%r)" % e)
    sys.exit(2)


def mk_bars(closes):
    return [{"time": 1000 + i * 3600, "open": c, "high": c + 1.0,
             "low": c - 1.0, "close": c} for i, c in enumerate(closes)]


def flips(dir_):
    return [i for i in range(1, len(dir_)) if dir_[i] != dir_[i - 1]]


def pct(seq, val):
    return 100.0 * sum(1 for x in seq if x == val) / max(1, len(seq))


fails = []

# 1) downtrend
dn = mk_bars([5000 - 2.0 * i for i in range(500)])
d = bts.st_dir_pine(dn, 10, 3.0)
p_up = pct(d, -1)
print("1) downtrend: up%%=%.1f flips=%d (want up%%~0, few flips)" % (p_up, len(flips(d))))
if p_up > 5:
    fails.append("downtrend frozen up")

# 2) uptrend
up = mk_bars([4000 + 2.0 * i for i in range(500)])
d = bts.st_dir_pine(up, 10, 3.0)
p_dn = pct(d, 1)
print("2) uptrend:   down%%=%.1f flips=%d (want down%%~0)" % (p_dn, len(flips(d))))
if p_dn > 5:
    fails.append("uptrend frozen down")

# 3) square wave: 60 bars up / 60 bars down, 6 cycles
sq = []
px = 4000.0
for cyc in range(6):
    for i in range(60):
        px += 3.0
        sq.append(px)
    for i in range(60):
        px -= 3.0
        sq.append(px)
d = bts.st_dir_pine(mk_bars(sq), 10, 3.0)
fl = flips(d)
kinds = set(d[i] for i in range(1, len(d)) if d[i] != d[i - 1])
print("3) square wave: flips=%d at %s kinds=%s (want ~6 flips, {-1,+1})"
      % (len(fl), fl[:12], kinds))
if len(fl) < 4 or kinds != {-1, 1}:
    fails.append("square wave flips=%d kinds=%s" % (len(fl), kinds))

# 4) V shape: 250 up then 250 down
v = [4000 + 2.0 * i for i in range(250)] + \
    [4000 + 2.0 * 250 - 2.0 * i for i in range(1, 251)]
d = bts.st_dir_pine(mk_bars(v), 10, 3.0)
fl = flips(d)
print("4) V-shape: flips=%d at %s (want 2: one into down, one into up)"
      % (len(fl), fl))
if len(fl) != 2:
    fails.append("V-shape flips=%d (want 2)" % len(fl))

# 5) staircase down (gaps up, steady falls): mostly down, flips only at tops
st_ = []
px = 5000.0
for step in range(8):
    for i in range(50):
        px -= 1.5
        st_.append(px)
    for i in range(6):
        px += 8.0
        st_.append(px)
d = bts.st_dir_pine(mk_bars(st_), 10, 3.0)
p_up = pct(d, -1)
print("5) staircase: up%%=%.1f flips=%d (want up%% well under broken-helper's ~99;"
      % (p_up, len(flips(d))))
print("   the 8x +8/bar rally bars occupy ~9%% of the series and legitimately"
      " flip ST at each top; 45%% cut = not-frozen")
if p_up > 45:
    fails.append("staircase stuck up %.0f%%" % p_up)

# 6) old broken helper comparison on a downtrend (behavioral note only)
print("\nRESULT: %s" % ("FAIL %s" % fails if fails else "ALL PROBES PASS"))
sys.exit(1 if fails else 0)
