r"""One-off: supres trail-config sweep on the walk-forward harness (H1 host).

Context (2026-10-01): walk-forward with the new per-family trails flagged
supres-T as BLEEDING (-$6.57 total, PF 0.56) while the fixed twin made
+$277. supres was NOT in backtest_trail_full_sweep.py (zero live trades so
far). Test a full config grid over 11 walk-forward windows to pick the right
trail for chart32 (supres-T) or justify retiring the twin.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
import backtest_walkforward as bwf
from backtest_new_candidates import row, run
from forward_test import closed_bars, load_env, strat_supres

WEEKS, WINDOW = 11, 14
CONFIGS = [
    (0.10, 0.3, 0.05, "deployed 0.10/0.3/0.05"),
    (0.2, 0.5, 0.10, "tight 0.2/0.5/0.10"),
    (0.3, 0.7, 0.15, "loose-928 0.3/0.7/0.15"),
    (0.5, 0.8, 0.20, "st-like 0.5/0.8/0.20"),
    (0.8, 1.0, 0.25, "aether 0.8/1.0/0.25"),
    (1.0, 1.2, 0.30, "widest 1.0/1.2/0.30"),
]


def main():
    load_env()
    for attempt in range(5):
        if mt5.initialize():
            break
        mt5.shutdown()
        time.sleep(10)
    else:
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    bars = closed_bars("XAUUSD", "H1", bwf.FETCH_DAYS * bwf.BPD["H1"] + bwf.WARM + 50)
    mt5.shutdown()
    if len(bars) < 1000:
        print("not enough H1 bars (%d)" % len(bars))
        return 1

    t_last = bars[-1]["time"]
    events = bwf.sig_events(strat_supres, bars, 0, t_last + 1, True)
    print("supres walk-forward trail sweep: %d events | %d windows of %dd"
          % (len(events), WEEKS, WINDOW))

    week, wlen = 7 * 86400, WINDOW * 86400
    windows = [(t_last - w * week - wlen, t_last - w * week)
               for w in range(WEEKS - 1, -1, -1)]

    fx_nets = []
    for t0, t1 in windows:
        ev = [e for e in events if t0 <= bars[e["sig_i"]]["time"] <= t1]
        trades, _ = run(ev, bars, dpu, cost, False)
        fx_nets.append(row(trades)[1])
    print("%-24s %s %9s %5s %5s %5s" %
          ("CONFIG", " ".join("w%-2d" % (WEEKS - i) for i in range(WEEKS)),
           "TOTAL", "n", "PF", "pos%"))

    def show(tag, nets, n_tr, pf, pospct):
        old3 = sum(nets[:3]) / 3.0
        new3 = sum(nets[-3:]) / 3.0
        print("%-24s %s %+9.2f %5d %5s %4.0f%%  decay %+7.2f"
              % (tag, " ".join("%+5.0f" % x for x in nets), sum(nets),
                 n_tr, pf, pospct, new3 - old3))

    show("fixed (control)", fx_nets, sum(1 for x in fx_nets), "n/a",
         100.0 * sum(1 for x in fx_nets if x > 0) / WEEKS)
    results = {}
    for act, dist, step, tag in CONFIGS:
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
        nets, n_tr, wins = [], 0, 0
        for t0, t1 in windows:
            ev = [e for e in events if t0 <= bars[e["sig_i"]]["time"] <= t1]
            trades, _ = run(ev, bars, dpu, cost, True)
            n, net, pf, _w = row(trades)
            nets.append(net)
            n_tr += n
            wins += 1 if net > 0 else 0
        results[tag] = sum(nets)
        show(tag, nets, n_tr,
             pf if isinstance(pf, str) else "%.2f" % pf,
             100.0 * wins / WEEKS)
    best = max(results, key=lambda t: results[t])
    dep = results[CONFIGS[0][3]]
    print("\nbest: %s (%+.2f) | deployed %+.2f | delta %+.2f | fixed %+.2f"
          % (best, results[best], dep, results[best] - dep, sum(fx_nets)))
    if results[best] < 0 < sum(fx_nets):
        print("VERDICT: no trail config is net-positive -- the TWIN (not the "
              "trail) is the problem; consider retiring supres-T")
    return 0


if __name__ == "__main__":
    sys.exit(main())
