"""Window-slice robustness check for the trailing-SL tightening.

The tightening probe (_trail_tighter_sweep.py) grades each config on ONE
pooled 100d number. A monotonic ladder on a pooled number can still be one
lucky regime. This re-runs the SAME configs on SEQUENTIAL, NON-OVERLAPPING
sub-windows of the same data and reports the per-window net side by side,
plus how many windows each config beats the deployed 0.10/0.3/0.05.

Decision rule: a config is only "robust tighter" if it wins the WINDOW COUNT,
not just the pooled sum, and if no single window carries the improvement.

Read-only. Runs ON THE VPS. Writes
C:/FTTest/logs/trail_tighter_windows.txt
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
import backtest_trailing_check as btc
import backtest_new_candidates as bnc
from backtest_new_candidates import market_events, run as bnc_run
from forward_test import (closed_bars, load_env, atr,
                          strat_breakout, strat_macross, strat_smc,
                          strat_squeeze, strat_trend)

bnc.walk_exit_trail = bae.walk_exit_trail

OUT = []
NWIN = 5
OUTPATH = r"C:\FTTest\logs\trail_tighter_windows.txt"


def emit(s=""):
    # flush to disk on EVERY line: this job runs unattended for minutes and a
    # crash/stall must still leave a readable partial result behind
    print(s, flush=True)
    OUT.append(s)
    try:
        with open(OUTPATH, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass


# deployed edge + the tightening ladder (trimmed to the decision-relevant set)
CANDS = [
    (0.10, 0.3, 0.05, "DEPLOYED 0.10/0.3/0.05"),
    (0.06, 0.20, 0.03, "tight    0.06/0.20/0.03"),
    (0.05, 0.15, 0.02, "tightest 0.05/0.15/0.02"),
    (0.04, 0.12, 0.02, "scalp    0.04/0.12/0.02"),
]

# aetherflow M30 live twin runs 0.2/0.5/0.10
CANDS_AE = [
    (0.2, 0.5, 0.10, "DEPLOYED 0.2/0.5/0.10"),
    (0.10, 0.3, 0.05, "tight    0.10/0.3/0.05"),
    (0.08, 0.25, 0.04, "tightest 0.08/0.25/0.04"),
]


def patch(act, dist, step):
    bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
    btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step


def raw_sigs(strat, bars):
    out = []
    for i in range(1, len(bars) - 1):
        r = strat(bars[max(0, i - 300):i + 1])
        if not r or r[0] != "entry":
            continue
        _, side, _sl, _tp = r
        a = atr(bars[max(0, i - 300):i + 1])
        if not a or a <= 0:
            continue
        out.append((i, side, a))
    return out


def slice_run(strat, ev, bars, dpu, cost, act, dist, step):
    """net, n for one config on one sub-window (events are passed in -- they
    do NOT depend on the trail params, so they are built once per window and
    reused by every config, keeping the comparison paired and cheap)."""
    patch(act, dist, step)
    tr, _ = bnc_run(ev, bars, dpu, cost, True)
    tr = tr or []
    return sum(tr), len(tr)


def window_case(name, strat, tf, bars, dpu, cost, configs):
    n = len(bars)
    cut = n // NWIN
    wins = [0] * len(configs)
    pooled = [0.0] * len(configs)
    pooled_n = [0] * len(configs)
    loo = [[] for _ in configs]  # leave-one-window-out totals
    all_nets = [[] for _ in configs]

    # build the window slices AND their event sets ONCE (trail-independent)
    segs, evs = [], []
    for w in range(NWIN):
        seg = bars[w * cut:(w + 1) * cut] if w < NWIN - 1 else bars[w * cut:]
        segs.append(seg)
        emit("   ... building window %d/%d signals" % (w + 1, NWIN))
        evs.append(market_events(raw_sigs(strat, seg), seg))

    emit("\n== %s (%s) : %d bars, %d windows of %d ==" % (name, tf, n, NWIN, cut))
    header = "   %-26s" % "config" + "".join("  W%-7d" % (w + 1) for w in range(NWIN))
    header += "     TOTAL      n"
    emit(header)

    for ci, (act, dist, step, tag) in enumerate(configs):
        nets = []
        ns = []
        for w in range(NWIN):
            net, k = slice_run(strat, evs[w], segs[w], dpu, cost, act, dist, step)
            nets.append(net)
            ns.append(k)
        # ci==0 IS the deployed baseline; every later config is scored against
        # its per-window nets (NOT against its own W1 -- that was a real bug)
        if ci == 0:
            dep_nets = list(nets)
        else:
            wins[ci] = sum(1 for w in range(NWIN)
                           if nets[w] > dep_nets[w] + 1e-9)
        pooled[ci] = sum(nets)
        pooled_n[ci] = sum(ns)
        all_nets[ci] = nets
        for w in range(NWIN):
            loo[ci].append(sum(nets[:w]) + sum(nets[w + 1:]))
        emit("   %-26s" % tag
             + "".join("%9.0f" % v for v in nets)
             + "%10.0f %5d" % (pooled[ci], pooled_n[ci]))

    dep = pooled[0]
    for ci, (act, dist, step, tag) in enumerate(configs):
        if ci == 0:
            continue
        worst_loo = min(loo[ci])
        worst_loo_dep = min(loo[0])
        verdict = ("ROBUST" if wins[ci] >= NWIN - 1 and worst_loo > worst_loo_dep
                   else ("MIXED" if wins[ci] >= NWIN // 2 else "WEAK"))
        emit("   -> %-26s beats deployed in %d/%d windows | pooled %+.0f (%+.0f vs dep)"
             " | worst leave-one-out %+.0f vs dep %+.0f  [%s]"
             % (tag, wins[ci], NWIN, pooled[ci], pooled[ci] - dep,
                worst_loo, worst_loo_dep, verdict))
        # every single window must be shown so a hidden loss window is visible
        emit("      per-window vs deployed: %s"
             % " ".join("W%d:%s" % (w + 1, "+" if all_nets[ci][w] >
                                      all_nets[0][w] + 1e-9 else "-")
                        for w in range(NWIN)))


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
        emit("mt5.initialize failed after 5 attempts")
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        emit("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04
    emit("TRAIL TIGHTENING -- WINDOW-SLICE ROBUSTNESS -- %s demo | cost $%.2f/trade"
         % (acc.login, cost))
    emit("%d sequential NON-OVERLAPPING windows; a config must win the window"
         % NWIN)
    emit("COUNT, not just the pooled sum, to count as robust.")

    # Each family runs as its OWN invocation (argv[1] or "all") so one slow
    # family cannot stall the rest of the verdict table.
    only = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    families = {
        "breakout": (strat_breakout, "M15", "M15", 100 * 96 + 300),
        "macross":  (strat_macross, "M30", "M30", 100 * 48 + 300),
        "smc":      (strat_smc, "M15", "M15", 100 * 96 + 300),
        "squeeze":  (strat_squeeze, "M15", "M15", 100 * 96 + 300),
        "trend":    (strat_trend, "H1", "H1", 100 * 24 + 300),
    }
    if only != "all" and only not in families:
        emit("unknown family %r (choose from %s or all)"
             % (only, ", ".join(sorted(families))))
        mt5.shutdown()
        return 1
    for key in sorted(families):
        if only not in ("all", key):
            continue
        strat, host_tf, label_tf, nbars = families[key]
        emit("\n########## FAMILY %s ##########" % key)
        window_case(key, strat, label_tf,
                    closed_bars("XAUUSD", host_tf, nbars), dpu, cost, CANDS)

    if only != "all":
        mt5.shutdown()
        emit("\n-> C:/FTTest/logs/trail_tighter_windows.txt")
        return 0

    # aetherflow M30, same slicing on the H4 feed
    h4 = closed_bars("XAUUSD", "H4", 100 * 6 + 300)
    cut = len(h4) // NWIN
    emit("\n== aetherflow-M30 (UT, H4 feed) : %d windows ==" % NWIN)
    nets = {t: [] for (_a, _b, _c, t) in CANDS_AE}
    for w in range(NWIN):
        seg = h4[w * cut:(w + 1) * cut] if w < NWIN - 1 else h4[w * cut:]
        eng = bae.Engines(seg)
        for act, dist, step, tag in CANDS_AE:
            patch(act, dist, step)
            tr, _ = bae.run_backtest(eng, seg, dpu, cost, "ut", True, False)
            nets[tag].append(sum(tr) if tr else 0.0)
    for act, dist, step, tag in CANDS_AE:
        emit("   %-26s" % tag + "".join("%9.0f" % v for v in nets[tag])
             + "%10.0f" % sum(nets[tag]))
    dep = nets["DEPLOYED 0.2/0.5/0.10"]
    for act, dist, step, tag in CANDS_AE[1:]:
        w_ = sum(1 for a, b in zip(nets[tag], dep) if a > b + 1e-9)
        emit("   -> %-26s beats deployed in %d/%d windows | pooled %+.0f (%+.0f vs dep)"
             % (tag, w_, NWIN, sum(nets[tag]), sum(nets[tag]) - sum(dep)))

    mt5.shutdown()
    emit("\n-> C:/FTTest/logs/trail_tighter_windows.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())