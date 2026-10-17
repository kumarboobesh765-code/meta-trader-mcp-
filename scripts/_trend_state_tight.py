"""Re-derive the trend family's per-trip expectation at the NEW tight trail.

Why this exists: EXPECT_AVG["trend"] was set to 4.56 -- the sweep's
+2675.49/534 = 5.01/trip with a 0.91 "walk-engine overstates trend" haircut
borrowed from the OLD trail. That haircut was measured at 0.10/0.3/0.05
(state machine 3.49 vs walk 3.84). Applying an old-trail haircut to a new
trail is an assumption, not a measurement, so this measures it directly:

  * runs the LIVE-PARITY state machine (re-entries, no exit-bar signal skip)
    at BOTH the old 0.10/0.3/0.05 and the deployed 0.05/0.15/0.02;
  * alongside the walk engine (busy lock) at the same two triples, so the
    walk/state RATIO can be recomputed per triple instead of assumed;
  * over the exact live window AND the 11x14d walk-forward, so the number
    used for grading is the same basis as before.

The state machine is the trustworthy one for trend (it reproduces the live
trip count); the walk engine is kept only to compute the ratio.

Read-only. Runs ON THE VPS. Writes C:/FTTest/logs/trend_state_tight.txt
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_walkforward import sig_events, FETCH_DAYS, BPD, WARM
from forward_test import closed_bars, load_env, strat_trend
from _trend_state_bt import atr_series14, run_state, stats

OUT = []
OUTPATH = r"C:\FTTest\logs\trend_state_tight.txt"

TRIPLES = [
    (0.10, 0.3, 0.05, "OLD 0.10/0.3/0.05"),
    (0.05, 0.15, 0.02, "DEPLOYED 0.05/0.15/0.02"),
    (0.04, 0.12, 0.02, "scalp 0.04/0.12/0.02"),
]


def emit(s=""):
    print(s, flush=True)
    OUT.append(s)
    try:
        with open(OUTPATH, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass


def main():
    load_env()
    if not mt5.initialize():
        emit("mt5.initialize failed: %s" % (mt5.last_error(),))
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
    bars = closed_bars("XAUUSD", "H1", FETCH_DAYS * BPD["H1"] + WARM + 50)
    mt5.shutdown()
    atr_at = atr_series14(bars)
    events = sig_events(strat_trend, bars, 0, bars[-1]["time"] + 1, True)
    emit("TREND PER-TRIP @ EACH TRAIL -- live-parity state machine vs walk engine")
    emit("bars=%d events=%d cost=$%.2f login=%s"
         % (len(bars), len(events), cost, acc.login))

    t_last = bars[-1]["time"]
    week, wlen = 7 * 86400, 14 * 86400
    wins = [(t_last - w * week - wlen, t_last - w * week)
            for w in range(10, -1, -1)]

    t0 = datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp()
    ev_live = [e for e in events if bars[e["sig_i"]]["time"] >= t0]

    def walk_net(ev, trailing=True):
        from backtest_new_candidates import run
        ts, _ = run(ev, bars, dpu, cost, trailing)
        ts = ts or []
        return sum(ts), len(ts)

    # --- A) walk-forward basis (the basis EXPECT_AVG was built on) ---
    emit("\n=== A) 11x14d walk-forward, per triple ===")
    emit("%-24s %-14s %10s %5s %9s %s"
         % ("triple", "engine", "net", "n", "per-trip", "walk/state ratio"))
    for act, dist, step, tag in TRIPLES:
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
        s_net = s_n = 0
        for (a, b) in wins:
            ev = [e for e in events if a <= bars[e["sig_i"]]["time"] <= b]
            ts = run_state(ev, bars, dpu, cost, True, atr_at)
            s_net += sum(ts)
            s_n += len(ts)
        w_net = w_n = 0
        for (a, b) in wins:
            ev = [e for e in events if a <= bars[e["sig_i"]]["time"] <= b]
            v, k = walk_net(ev, True)
            w_net += v
            w_n += k
        ratio = (s_net / w_net) if w_net else float("nan")
        emit("%-24s %-14s %+10.2f %5d %+9.2f"
             % (tag, "state trail", s_net, s_n,
                (s_net / s_n) if s_n else 0.0))
        emit("%-24s %-14s %+10.2f %5d %+9.2f  %.3f"
             % ("", "walk trail", w_net, w_n,
                (w_net / w_n) if w_n else 0.0, ratio))

    # --- B) fixed twin control, same basis ---
    emit("\n=== B) 11x14d walk-forward, FIXED twin (control) ===")
    for act, dist, step, tag in TRIPLES[:1]:
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
        s_net = s_n = 0
        for (a, b) in wins:
            ev = [e for e in events if a <= bars[e["sig_i"]]["time"] <= b]
            ts = run_state(ev, bars, dpu, cost, False, atr_at)
            s_net += sum(ts)
            s_n += len(ts)
        emit("%-24s %-14s %+10.2f %5d %+9.2f"
             % (tag, "state fixed", s_net, s_n, (s_net / s_n) if s_n else 0.0))

    # --- C) exact live window ---
    emit("\n=== C) exact live window (live actuals: trail n=27 -146.06) ===")
    for act, dist, step, tag in TRIPLES:
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
        for label, tr in (("state trail", True), ("state fixed", False)):
            ts = run_state(ev_live, bars, dpu, cost, tr, atr_at)
            emit("   %-24s %-12s %s" % (tag, label, stats(ts)))

    emit("\nVERDICT BASIS: use the DEPLOYED row of section A 'state trail'")
    emit("per-trip as EXPECT_AVG['trend']; the ratio is measured, not assumed.")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())