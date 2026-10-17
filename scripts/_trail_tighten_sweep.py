r"""Trail-tightening sweep (2026-09-30): compare the deployed 0.3/0.7/0.15
twin trail against tighter candidates over the last 90d, per family, using
the walkforward events machinery (same engines as the EAs mirror).

Candidates (activate/dist/step, ATR multiples):
  BASE 0.30/0.70/0.15   T1 0.25/0.55/0.10   T2 0.25/0.60/0.10   T3 0.20/0.50/0.10

Run: python C:/FTTest/scripts/_trail_tighten_sweep.py
"""
import os
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_walkforward import (FAMILIES, WARM, sig_events,
                                  sig_supertrend_wf, BPD, FETCH_DAYS)
from forward_test import closed_bars, load_env

CANDIDATES = [("BASE .30/.70/.15", 0.30, 0.70, 0.15),
              ("T1   .25/.55/.10", 0.25, 0.55, 0.10),
              ("T2   .25/.60/.10", 0.25, 0.60, 0.10),
              ("T3   .20/.50/.10", 0.20, 0.50, 0.10)]
AETHER_CANDIDATES = [("BASE 1.0/1.2/0.3", 1.0, 1.2, 0.3),
                     ("T1   0.8/1.0/0.25", 0.8, 1.0, 0.25)]


def main():
    load_env()
    ok = False
    for attempt in range(5):
        if mt5.initialize():
            ok = True
            break
        print("attach %d failed: %s" % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        time.sleep(10)
    if not ok:
        return 3
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        return 2
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    need = {}
    for name, tf, fn, fl in FAMILIES:
        need[tf] = max(need.get(tf, 0), FETCH_DAYS * BPD[tf] + WARM + 50)
    series = {tf: closed_bars("XAUUSD", tf, n) for tf, n in need.items()}
    h1 = series["H1"]
    trs_h1 = ba.tr_series(h1)
    mt5.shutdown()

    t_last = h1[-1]["time"]
    t90 = t_last - 90 * 86400

    # build events once per family over the full series, slice to 90d
    fams = []
    for name, tf, fn, fl in FAMILIES:
        bars = series[tf]
        ev = [e for e in sig_events(fn, bars, t90, t_last + 1, fl)]
        fams.append((name, bars, ev))
    fams.append(("supertrend", h1,
                 [e for e in sig_supertrend_wf(h1, t90, t_last + 1, trs_h1)]))

    print("Trail-tighten sweep | XAUUSD 90d | trail twins only | cost $%.2f"
          % cost)
    print("%-18s" % "FAMILY", end="")
    for label, _, _, _ in CANDIDATES:
        print("%19s" % label, end="")
    print("   (n per setting)")

    totals = {label: 0.0 for label, _, _, _ in CANDIDATES}
    for name, bars, ev in fams:
        print("%-18s" % name, end="")
        n_ref = 0
        for label, act, dist, step in CANDIDATES:
            ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
            trades, mods = ba_run(ev, bars, dpu, cost)
            net = sum(t for t in trades)
            n_ref = len(trades)
            totals[label] += net
            print("%+19.2f" % net, end="")
        print("   n=%d" % n_ref)
    print("%-18s" % "TOTAL", end="")
    for label, _, _, _ in CANDIDATES:
        print("%+19.2f" % totals[label], end="")
    print()
    return 0


def ba_run(events, bars, dpu, cost):
    """Trail-only run via the candidates' shared engine."""
    from backtest_new_candidates import run
    trades, mods = run(events, bars, dpu, cost, True)
    return trades, mods


if __name__ == "__main__":
    sys.exit(main())
