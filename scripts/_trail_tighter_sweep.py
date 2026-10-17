"""Trailing-SL tightening probe: BEYOND the deployed 0.10/0.3/0.05.

The 2026-10-01 full sweep already found "tightest 0.10/0.3/0.05" the winner
for 7 M15 families and that verdict is DEPLOYED. The user reports positions
"going good in profit then reversing to loss", i.e. a trail too slow to
protect open profit. This probe re-runs the SAME harnesses on FRESH data but
extends the grid PAST the deployed edge -- snappier activation (engage the
trail sooner), tighter distance (lock more), and a BE-style early lock --
to answer whether tightening FURTHER helps or starts cutting winners short.

Read-only. Runs ON THE VPS. Output appended to
C:/FTTest/logs/trail_tighter_sweep.txt by the caller.
"""
import contextlib
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
import backtest_supertrend as bst
import backtest_trailing_check as btc
import backtest_new_candidates as bnc
from backtest_new_candidates import market_events, run as bnc_run
from forward_test import (closed_bars, load_env, atr,
                          strat_breakout, strat_macross, strat_smc,
                          strat_squeeze, strat_trend)

# bnc.run calls bnc.walk_exit_trail; rebind it to bae's fn object so the
# bae.TRAIL_* globals we patch actually reach the M15/M30/H1 path.
bnc.walk_exit_trail = bae.walk_exit_trail

OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


# deployed edge + progressively tighter/faster. Lower ACT = engage sooner;
# lower DIST = trail sits closer (locks more); lower STEP = ratchets in
# smaller increments (finer).
TIGHTER_FT = [
    (0.10, 0.3, 0.05, "DEPLOYED 0.10/0.3/0.05"),
    (0.08, 0.25, 0.04, "tighter 0.08/0.25/0.04"),
    (0.06, 0.20, 0.03, "tight 0.06/0.20/0.03"),
    (0.05, 0.15, 0.02, "tightest 0.05/0.15/0.02"),
    (0.10, 0.3, 0.02, "fast-step 0.10/0.3/0.02"),
    (0.10, 0.2, 0.05, "tight-dist 0.10/0.2/0.05"),
    (0.04, 0.12, 0.02, "scalp 0.04/0.12/0.02"),
]

# aetherflow M30 is a live trail twin at 0.2/0.5/0.10 (0.8/1.0/0.25 is H4).
TIGHTER_AE = [
    (0.2, 0.5, 0.10, "DEPLOYED 0.2/0.5/0.10"),
    (0.15, 0.4, 0.08, "tighter 0.15/0.4/0.08"),
    (0.10, 0.3, 0.05, "tight 0.10/0.3/0.05"),
    (0.08, 0.25, 0.04, "tightest 0.08/0.25/0.04"),
    (0.2, 0.4, 0.05, "fast-step 0.2/0.4/0.05"),
]


def patch(act, dist, step):
    bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
    btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step


def raw_sigs(strat, bars):
    """[(i, side, a)] per bar from a forward_test strat_ fn (same as the
    full-sweep's market_events feeder)."""
    out = []
    a_cache = None
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


def m15_case(name, strat, tf, bars, dpu, cost, configs):
    ev = market_events(raw_sigs(strat, bars), bars)
    fx, _ = bnc_run(ev, bars, dpu, cost, False)
    emit("\n-- %s (%s) fixed=%+.2f --" % (name, tf, sum(fx) if fx else 0.0))
    for act, dist, step, tag in configs:
        patch(act, dist, step)
        tr, mods = bnc_run(ev, bars, dpu, cost, True)
        net = sum(tr) if tr else 0.0
        n = len(tr) if tr else 0
        win = sum(1 for t in (tr or []) if t > 0)
        pf = ""
        if tr:
            g = sum(t for t in tr if t > 0)
            l = abs(sum(t for t in tr if t <= 0))
            pf = " PF=%.2f" % (g / l) if l > 0 else " PF=inf"
        dead = " <DEAD>" if mods == 0 and net >= 0 else ""
        emit("   %-30s n=%-4d net=%+9.2f win=%2.0f%%%s mods=%-4d%s"
             % (tag, n, net, (100.0 * win / n) if n else 0, pf, mods, dead))


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
    emit("TRAIL TIGHTENING PROBE (beyond deployed 0.10/0.3/0.05) -- %s demo | "
         "cost $%.2f/trade | pessimistic replay" % (acc.login, cost))
    emit("lower ACT engages sooner, lower DIST locks more profit, "
         "lower STEP ratchets finer")

    # M15-host families
    m15 = closed_bars("XAUUSD", "M15", 100 * 96 + 300)
    m30 = closed_bars("XAUUSD", "M30", 100 * 48 + 300)
    m15_case("breakout", strat_breakout, "M15", m15, dpu, cost, TIGHTER_FT)
    m15_case("macross", strat_macross, "M30", m30, dpu, cost, TIGHTER_FT)
    m15_case("smc", strat_smc, "M15", m15, dpu, cost, TIGHTER_FT)
    m15_case("squeeze", strat_squeeze, "M15", m15, dpu, cost, TIGHTER_FT)
    m15_case("trend", strat_trend, "H1", closed_bars("XAUUSD", "H1", 100 * 24 + 300),
             dpu, cost, TIGHTER_FT)

    # aetherflow M30 (UT-only) -- the live trailing M30 twin
    #
    # 2026-10-02 CAVEAT: this block grades the M30 leg on the H4 FEED, which
    # is NOT what the live M30 twins (950002/960002, charts 19/20) run on.
    # Its negative result here is therefore a FEED MISMATCH, not a verdict on
    # the M30 strategy -- see scripts/_aetherflow_m30_diag.py, where the same
    # 0.2/0.5/0.10 trail on the TRUE M30 feed is +$267 PF 1.44 (n=120).
    # Do not use these rows to judge aetherflow-M30.
    h4 = closed_bars("XAUUSD", "H4", 90 * 6 + 300)
    trs_h4 = bae.tr_series(h4)
    eng = bae.Engines(h4)
    emit("\n-- aetherflow-M30 (UT, H4 feed as deployed) --")
    for act, dist, step, tag in TIGHTER_AE:
        patch(act, dist, step)
        tr, _ = bae.run_backtest(eng, h4, dpu, cost, "ut", True, False)
        net = sum(tr) if tr else 0.0
        n = len(tr) if tr else 0
        emit("   %-30s n=%-4d net=%+9.2f" % (tag, n, net))

    mt5.shutdown()
    with open(r"C:\FTTest\logs\trail_tighter_sweep.txt", "w",
              encoding="utf-8") as f:
        f.write("\n".join(OUT))
    emit("\n-> C:/FTTest/logs/trail_tighter_sweep.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
