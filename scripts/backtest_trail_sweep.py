r"""Trailing-parameter sweep: is a FASTER trailing SL more profitable?

Runs the exact trail walk from backtest_trailing_check.py over a small grid of
(activate, distance, step) ATR configs on 30d M15 data, per (symbol, strategy),
and reports where a faster/tighter trail beats the live baseline (1.0/1.2/0.3).
Fixed-twin results are the control. Same pessimistic fills as the harness.

Usage (VPS): python C:/FTTest/scripts/backtest_trail_sweep.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_trailing_check as bt
from forward_test import SYMBOLS, closed_bars

COMMISSION = 0.04
BARS_REQUEST = bt.BARS_REQUEST

# (activate, dist, step) -- baseline first
CONFIGS = [
    (1.0, 1.2, 0.3, "baseline 1.0/1.2/0.3 (live)"),
    (0.6, 0.9, 0.25, "faster 0.6/0.9/0.25"),
    (0.3, 0.7, 0.15, "tightest 0.3/0.7/0.15"),
    (0.6, 1.2, 0.2, "early-act 0.6/1.2/0.2"),
    (1.0, 1.6, 0.3, "wider 1.0/1.6/0.3 (control)"),
]


def row_sum(trades):
    return sum(trades) if trades else 0.0


def main():
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        mt5.shutdown()
        return 1
    print("trail sweep on %s (30d M15, pessimistic fills)" % acc.server)

    results = {}   # (sym, strat) -> {cfg_name: trail_net}
    fixed_net = {}  # (sym, strat) -> fixed twin net
    names = list(bt.SIGNAL_FNS) + list(bt.DUAL_MODES)
    for s in SYMBOLS:
        mt5.symbol_select(s, True)
        si = mt5.symbol_info(s)
        if si is None:
            continue
        dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
        bars = closed_bars(s, "M15", BARS_REQUEST)
        if len(bars) < 400:
            print("%-8s not enough bars" % s)
            continue
        for name in names:
            if name in bt.SIGNAL_FNS:
                fx, _ = bt.run_signal(bt.SIGNAL_FNS[name], bars, dpu, False)
                fixed_net[(s, name)] = row_sum(fx)
                results[(s, name)] = {}
                for act, dist, step, tag in CONFIGS:
                    bt.TRAIL_ACTIVATE, bt.TRAIL_DIST, bt.TRAIL_STEP = act, dist, step
                    tr, _m = bt.run_signal(bt.SIGNAL_FNS[name], bars, dpu, True)
                    results[(s, name)][tag] = row_sum(tr)
            else:
                fx, _ = bt.run_dual(bars, dpu, bt.DUAL_MODES[name], False)
                fixed_net[(s, name)] = row_sum(fx)
                results[(s, name)] = {}
                for act, dist, step, tag in CONFIGS:
                    bt.TRAIL_ACTIVATE, bt.TRAIL_DIST, bt.TRAIL_STEP = act, dist, step
                    tr, _m = bt.run_dual(bars, dpu, bt.DUAL_MODES[name], True)
                    results[(s, name)][tag] = row_sum(tr)
        print("  %s done" % s)
    mt5.shutdown()

    base_tag = CONFIGS[0][3]
    print("\n%-8s %-9s %9s | " % ("SYMBOL", "STRAT", "fixed") +
          " | ".join("%12s" % c[3].split()[0] + "/" + c[3].split()[1]
                     for c in CONFIGS) + " | best")
    flips = []
    for key in sorted(results):
        s, name = key
        nets = results[key]
        best_tag = max(nets, key=lambda t: nets[t])
        fx = fixed_net.get(key, 0.0)
        if best_tag != base_tag and nets[best_tag] - nets[base_tag] > 1.0:
            flips.append((key, best_tag, nets[base_tag], nets[best_tag], fx))
        print("%-8s %-9s %9.2f | " % (s, name, fx) +
              " | ".join("%12.2f" % nets[c[3]] for c in CONFIGS) +
              " | %s" % best_tag.split()[0] + "/" + best_tag.split()[1])
    print("\nslots where a different config beats the live baseline by >$1:")
    if not flips:
        print("  NONE -- the live trailing rule (1.0/1.2/0.3) is already optimal")
    for key, tag, base, best, fx in flips:
        print("  %-9s %-9s  live %+.2f -> %s %+.2f  (fixed %+.2f)"
              % (key[0], key[1], base, tag.split()[0] + "/" + tag.split()[1],
                 best, fx))
    # aggregate: trail-managed slots only (live WINNER == trail)
    agg = {c[3]: 0.0 for c in CONFIGS}
    for key, nets in results.items():
        if key[1] in bt.DUAL_MODES:
            pass
        for c in CONFIGS:
            agg[c[3]] += nets[c[3]]
    print("\nall-slot totals per config:")
    for c in CONFIGS:
        print("  %-32s %+.2f" % (c[3], agg[c[3]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
