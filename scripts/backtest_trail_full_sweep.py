r"""Full-coverage trailing-SL sweep: EVERY trailing-managed strategy, one run.

Motivation (user, 2026-10-01): "a lot of strategies' trailing SL is very slow
or not working -- tighten the trailing SL and check in backtest that every
trailing SL works perfectly."

Sections (all use the SAME pessimistic bar-replay rules as the live harnesses:
signals on closed bars, entry next open, SL tested before trail updates,
1-bar trail lag, spread + $0.04/0.01-lot RT):

  1. m15-seven   breakout/meanrev/macross/smc/squeeze (run_signal) +
                 straddle/london (run_dual)            [backtest_trailing_check]
  2. h1-hosted   trend / trendpullback (donchian == breakout engine, same
                 walker -> noted, not duplicated)      [forward_test.strat_*]
  3. other-hosts aetherflow M30 + aetherflow H4 (UT-only, the live configs),
                 supertrend H1 (5,2.0), liquiditysweep H4 (48/0.20/0.05,
                 dir-agnostic)                          [backtest_aetherflow walker]
  4. smvp        M1 supply/demand: R-based BE+chandelier trail, module
                 constants patched per config           [backtest_smvp]

VERDICT so far (30d M15, 2026-10-01 run): "tightest 0.10/0.3/0.05" beat the
live 0.2/0.5/0.10 on EVERY trailing strategy (trend +$759, straddle +$256,
breakout +$112, macross +$77, meanrev +$51, smc +$45, squeeze +$42).

Trail configs (baseline = LIVE value first, then tighter):
  FTTest twins (0.2/0.5/0.10 live since 9/30):
      0.2/0.5/0.10 | 0.15/0.4/0.08 | 0.10/0.3/0.05 | 0.2/0.35/0.10 | 0.3/0.7/0.15
  Aether twins (0.8/1.0/0.25 live):
      0.8/1.0/0.25 | 0.5/0.8/0.20 | 0.3/0.6/0.15 | 0.2/0.5/0.10 | 1.0/1.2/0.30
  SMVP (start 1.0R / dist 1.0 ATR / chandelier-12 live):
      1.0R/1.0 | 0.8R/1.0 | 1.0R/0.8 | 0.8R/0.8   (chandelier always on; the
      EA input is a bool the harness inlines, not a patchable constant)

Dead-trail detection: a config that produced ZERO trail modifications while
the fixed twin had winners is flagged -- "trail never engaged" (too slow or
TF too coarse), which is the "not working" symptom.

Usage (VPS): python C:/FTTest/scripts/backtest_trail_full_sweep.py
             [--skip-m15] [--only hosts|smvp]
Output is also written to C:/FTTest/logs/trail_full_sweep.txt
"""

import argparse
import contextlib
import io
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
import backtest_smvp as bsm
import backtest_trailing_check as btc
import backtest_supertrend as bst
import backtest_liquiditysweep as bls
import backtest_new_candidates as bnc
from backtest_new_candidates import market_events, run as bnc_run
from forward_test import closed_bars, load_env, strat_trend, strat_trendpullback

# bnc and bls freeze walk_exit_trail via from-imports; rebind them to the SAME
# function object so setting bae.TRAIL_* per config reaches every harness path
# (the original fn reads bae's module globals at call time).
bnc.walk_exit_trail = bae.walk_exit_trail
bls.walk_exit_trail = bae.walk_exit_trail

FT_CONFIGS = [
    (0.2, 0.5, 0.10, "live 0.2/0.5/0.10"),
    (0.15, 0.4, 0.08, "tight 0.15/0.4/0.08"),
    (0.10, 0.3, 0.05, "tightest 0.10/0.3/0.05"),
    (0.2, 0.35, 0.10, "tight-dist 0.2/0.35/0.10"),
    (0.3, 0.7, 0.15, "loose-928 0.3/0.7/0.15"),
]
AE_CONFIGS = [
    (0.8, 1.0, 0.25, "live 0.8/1.0/0.25"),
    (0.5, 0.8, 0.20, "tight 0.5/0.8/0.20"),
    (0.3, 0.6, 0.15, "tightest 0.3/0.6/0.15"),
    (0.2, 0.5, 0.10, "fttest 0.2/0.5/0.10"),
    (1.0, 1.2, 0.30, "loose 1.0/1.2/0.30"),
]
SMVP_CONFIGS = [
    (1.00, 1.00, "live 1.0R/1.0ATR"),
    (0.80, 1.00, "earlier 0.8R/1.0ATR"),
    (1.00, 0.80, "tighter 1.0R/0.8ATR"),
    (0.80, 0.80, "both 0.8R/0.8ATR"),
]

OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


def rowsum(trades):
    return sum(trades) if trades else 0.0


def table(family, results, fixed_net, baseline_tag, configs):
    """results[(name)][tag] = (n, net, mods); fixed_net[(name)] = net."""
    emit("")
    emit("== %s ==" % family)
    emit("%-18s %9s | %s" % ("STRATEGY", "fixed",
                             " | ".join("%16s" % c[3] for c in configs)))
    for name in sorted(results):
        fx = fixed_net.get(name)
        cells = []
        for c in configs:
            n, net, mods = results[name][c[3]]
            dead = " <DEAD>" if (mods == 0 and fx and fx > 0 and net >= 0) else ""
            cells.append("%16s" % ("%+.1f/%d%s" % (net, n, dead)))
        emit("%-18s %9s | %s" % (name,
                                 ("%+.1f" % fx) if fx is not None else "n/a",
                                 " | ".join(cells)))
    for name in sorted(results):
        nets = {c[3]: results[name][c[3]][1] for c in configs}
        best = max(nets, key=lambda t: nets[t])
        base = nets[baseline_tag]
        if best != baseline_tag and nets[best] - base > 1.0:
            emit("  WINNER %-14s %s: %+.2f -> %+.2f (%+.2f)"
                 % (name, best, base, nets[best], nets[best] - base))
        elif best == baseline_tag:
            emit("  ok     %-14s live config already best (%+.2f)"
                 % (name, base))
        else:
            emit("  ~      %-14s no config beats live by >$1 (best %s %+.2f)"
                 % (name, best, nets[best]))


def run_m15_section(dpu):
    bars15 = closed_bars("XAUUSD", "M15", btc.BARS_REQUEST)
    if len(bars15) < 400:
        emit("not enough M15 bars (%d)" % len(bars15))
        return
    res15, fx15 = {}, {}
    for name in sorted(btc.SIGNAL_FNS):
        f, _ = btc.run_signal(btc.SIGNAL_FNS[name], bars15, dpu, False)
        fx15[name] = rowsum(f)
        res15[name] = {}
        for act, dist, step, tag in FT_CONFIGS:
            btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step
            tr, mods = btc.run_signal(btc.SIGNAL_FNS[name], bars15, dpu, True)
            res15[name][tag] = (len(tr), rowsum(tr), mods)
    for name in sorted(btc.DUAL_MODES):
        f, _ = btc.run_dual(bars15, dpu, btc.DUAL_MODES[name], False)
        fx15[name] = rowsum(f)
        res15[name] = {}
        for act, dist, step, tag in FT_CONFIGS:
            btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step
            tr, mods = btc.run_dual(bars15, dpu, btc.DUAL_MODES[name], True)
            res15[name][tag] = (len(tr), rowsum(tr), mods)
    # trend / trendpullback ride the same walker (H1 logic aggregated from M15)
    for name, fn in (("trend", strat_trend),
                     ("trendpullback", strat_trendpullback)):
        f, _ = btc.run_signal(fn, bars15, dpu, False)
        fx15[name] = rowsum(f)
        res15[name] = {}
        for act, dist, step, tag in FT_CONFIGS:
            btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step
            tr, mods = btc.run_signal(fn, bars15, dpu, True)
            res15[name][tag] = (len(tr), rowsum(tr), mods)
    emit("\n(donchian = breakout engine identically, same trail verdict -> "
          "not duplicated)")
    table("M15-host twins (FTTest 0.2/0.5/0.10)", res15, fx15,
          FT_CONFIGS[0][3], FT_CONFIGS)


def run_hosts_section(dpu, cost):
    BPD_EXT = dict(bae.BARS_PER_DAY, H4=6)   # aetherflow harness lacks H4
    res_oth, fx_oth = {}, {}

    # aetherflow M30 (live host TF) + H4 -- run_backtest returns (trades, mods)
    for tf, days in (("M30", 30), ("H4", 60)):
        nbars = days * BPD_EXT[tf] + 300
        barsx = closed_bars("XAUUSD", tf, nbars)
        if len(barsx) < 400:
            emit("  aetherflow-%s: not enough bars (%d)" % (tf, len(barsx)))
            continue
        eng = bae.Engines(barsx)
        fx, _ = bae.run_backtest(eng, barsx, dpu, cost, "ut", False, False)
        fx_oth["aetherflow-" + tf] = rowsum(fx)
        res_oth["aetherflow-" + tf] = {}
        for act, dist, step, tag in AE_CONFIGS:
            bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
            tr, mods = bae.run_backtest(eng, barsx, dpu, cost, "ut", True, False)
            res_oth["aetherflow-" + tf][tag] = (len(tr), rowsum(tr), mods)

    # supertrend H1 (5, 2.0 -- the live pair); bnc.run returns (trades, mods)
    bars_h1 = closed_bars("XAUUSD", "H1", bst.FETCH_DAYS * bst.BPD["H1"] + 300)
    if len(bars_h1) >= 600:
        trs = []
        prev_close = None
        for b in bars_h1:
            pc = b["close"] if prev_close is None else prev_close
            trs.append(max(b["high"] - b["low"],
                           abs(b["high"] - pc), abs(b["low"] - pc)))
            prev_close = b["close"]
        t0 = bars_h1[-1]["time"] - 60 * 86400
        sigs = bst.sig_supertrend(bars_h1, trs, t0, 5, 2.0)
        events = market_events(sigs, bars_h1)
        f, _ = bnc_run(events, bars_h1, dpu, cost, False)
        fx_oth["supertrend-H1"] = rowsum(f)
        res_oth["supertrend-H1"] = {}
        for act, dist, step, tag in AE_CONFIGS:
            bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
            tr, mods = bnc_run(events, bars_h1, dpu, cost, True)
            res_oth["supertrend-H1"][tag] = (len(tr), rowsum(tr), mods)

    # liquiditysweep H4 (48/0.20/0.05, dir-agnostic); run_strategy -> trades only
    bars_h4 = closed_bars("XAUUSD", "H4", bls.FETCH_DAYS * bls.BPD + 300)
    if len(bars_h4) >= 100:
        trs4 = bae.tr_series(bars_h4)
        t04 = bars_h4[-1]["time"] - 90 * 86400
        sigs4 = bls.sweep_signals(bars_h4, trs4, 48, 0.20, 0.05, t04, False)

        def ls_run(trailing):
            return bls.run_strategy(bars_h4, trs4, dpu, cost, sigs4, trailing)

        f = ls_run(False)
        fx_oth["liquiditysweep-H4"] = rowsum(f)
        res_oth["liquiditysweep-H4"] = {}
        for act, dist, step, tag in AE_CONFIGS:
            bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
            tr = ls_run(True)
            res_oth["liquiditysweep-H4"][tag] = (len(tr), rowsum(tr), -1)

    table("other-host twins (Aether 0.8/1.0/0.25)", res_oth, fx_oth,
          AE_CONFIGS[0][3], AE_CONFIGS)


def run_smvp_section():
    emit("")
    emit("== SMVP (R-based BE+chandelier trail, chandelier always on) ==")
    smvp_rows = {}
    for start_r, atr_m, tag in SMVP_CONFIGS:
        bsm.TRAIL_START_R = start_r
        bsm.TRAIL_ATR = atr_m
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bsm.main()
        txt = buf.getvalue()
        m = re.search(r"(\d+) closed trades", txt)
        n = int(m.group(1)) if m else 0
        mr = re.search(r"fixed 0\.01 lot\s+net=\$\s*([-\d.]+)\s+PF=([\dinf.]+)",
                       txt)
        net = float(mr.group(1)) if mr else 0.0
        pf = mr.group(2) if mr else "n/a"
        smvp_rows[tag] = (n, net, pf)
        emit("%-24s %6d %+9.2f  PF=%s" % (tag, n, net, pf))
    best = max(smvp_rows, key=lambda t: smvp_rows[t][1])
    live_tag = SMVP_CONFIGS[0][2]
    emit("  best: %s (%+.2f) | live %s = %+.2f | delta %+.2f"
         % (best, smvp_rows[best][1], live_tag, smvp_rows[live_tag][1],
            smvp_rows[best][1] - smvp_rows[live_tag][1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-m15", action="store_true",
                    help="skip section 1+2 (verdict known: tightest wins)")
    ap.add_argument("--only", choices=["hosts", "smvp", "m15"], default=None,
                    help="run a single remaining section")
    args = ap.parse_args()

    load_env()
    ok = False
    for attempt in range(5):
        if mt5.initialize():
            ok = True
            break
        print("attach attempt %d failed: %s -- retrying in 10s"
              % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        time.sleep(10)
    if not ok:
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    emit("TRAIL FULL SWEEP -- %s %s (demo ok) | XAUUSD dpu=%.2f cost=%.2f/trade"
         % (acc.login, acc.server, dpu, cost))
    emit("pessimistic replay: SL before trail, 1-bar lag, closed-bar signals")

    if args.only == "hosts":
        run_hosts_section(dpu, cost)
    elif args.only == "m15":
        run_m15_section(dpu)
    elif args.only == "smvp":
        run_smvp_section()
    else:
        if not args.skip_m15:
            run_m15_section(dpu)
        run_hosts_section(dpu, cost)
        run_smvp_section()

    mt5.shutdown()
    with open("C:/FTTest/logs/trail_full_sweep.txt", "a") as fh:
        fh.write("\n".join(OUT) + "\n\n")
    print("\nappended -> C:/FTTest/logs/trail_full_sweep.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
