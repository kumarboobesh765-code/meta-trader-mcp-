"""Parity gate: the optimised causal series vs the naive per-bar computation
on REAL VPS data. If these disagree, the speedup changed the strategy and
every backtest number is suspect. Prints the first divergence."""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

spec = importlib.util.spec_from_file_location(
    "bs", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "backtest_swing.py"))
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def naive_events(bars, bpd):
    """The original O(n^2) formulation, verbatim in logic."""
    n = len(bars)
    out = []
    nh = n // bpd
    if nh < bs.EMA_BIAS + 5:
        return out
    hc = [bars[n - (nh - h) * bpd + (bpd - 1)]["close"] for h in range(nh)]
    closes = [b["close"] for b in bars]
    k = 2.0 / (bs.EMA_PULL + 1)
    acc = sum(closes[:bs.EMA_PULL]) / bs.EMA_PULL
    e21_series = [None] * (bs.EMA_PULL - 1) + [acc]
    for c in closes[bs.EMA_PULL:]:
        acc = c * k + acc * (1 - k)
        e21_series.append(acc)
    for i in range(max(bs.EMA_BIAS + bs.EMA_PULL + 2, 60), n):
        bi = (i + 1) // bpd
        if bi < bs.EMA_BIAS + 2 or bi > nh:
            continue
        e50_prev = bs.ema(hc[:bi - 1], bs.EMA_BIAS)
        if e50_prev is None:
            continue
        if hc[bi - 1] > e50_prev:
            up = True
        elif hc[bi - 1] < e50_prev:
            up = False
        else:
            continue
        a = bs.atr(bars[:i + 1])
        if not a:
            continue
        r = bs.rsi(closes[:i + 1])
        if r is None:
            continue
        e21 = e21_series[i]
        if e21 is None:
            continue
        b = bars[i]
        px = b["close"]
        if up and b["low"] <= e21 and b["close"] > b["open"] and r >= bs.RSI_MIN:
            out.append((i, "buy"))
        elif (not up) and b["high"] >= e21 and b["close"] < b["open"] \
                and r <= 100 - bs.RSI_MIN:
            out.append((i, "sell"))
    return out


if not mt5.initialize():
    raise SystemExit("init failed %r" % mt5.last_error())

for tf, tfc in (("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)):
    rates = mt5.copy_rates_from_pos("XAUUSD", tfc, 1, 60 * 96)
    bars = [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"]} for r in rates]
    bpd = bs.BARS_PER_DAY[tf]
    fast = [(e["sig_i"], e["side"]) for e in bs.swing_events(bars, bpd)]
    slow = naive_events(bars, bpd)
    same = fast == slow
    print("%s bars=%d  fast=%d slow=%d  IDENTICAL=%s"
          % (tf, len(bars), len(fast), len(slow), same))
    if not same:
        for i, (f, s) in enumerate(zip(fast, slow)):
            if f != s:
                print("  first divergence at #%d: fast=%r slow=%r" % (i, f, s))
                break
        else:
            print("  one is a prefix of the other; lengths %d vs %d"
                  % (len(fast), len(slow)))
mt5.shutdown()