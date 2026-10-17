"""Ad-hoc: strat_trend backtest over the EXACT live window (default 2026-09-29).

Reuses backtest_walkforward.sig_events + backtest_new_candidates.run so the
numbers are directly comparable to the walk-forward expectation (+$3.84/trip,
trail twin). Purpose: retire-or-fix verdict for the trend family.

Runs ON THE VPS (needs MT5 attach). Read-only.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_new_candidates import run, row
from backtest_walkforward import sig_events, TRAIL_FTTEST, FETCH_DAYS, BPD, WARM
from forward_test import closed_bars, load_env, strat_trend


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-29")
    args = ap.parse_args()

    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04
    bars = closed_bars("XAUUSD", "H1", FETCH_DAYS * BPD["H1"] + WARM + 50)
    mt5.shutdown()

    t0 = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp()
    t1 = bars[-1]["time"] + 1
    events = sig_events(strat_trend, bars, t0, t1, True)
    span = (bars[-1]["time"] - t0) / 86400.0
    print("strat_trend window %s -> now (%.1fd) | H1 bars=%d | events=%d | "
          "cost=$%.2f/trade" % (args.since, span, len(bars), len(events), cost))
    print("last H1 bar: %s"
          % datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc))

    ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = TRAIL_FTTEST
    for twin, trailing in (("trail", True), ("fixed", False)):
        trades, mods = run(events, bars, dpu, cost, trailing)
        n, net, pf, w = row(trades)
        print("\n%-5s twin: n=%d net=%+.2f win=%s%% PF=%s trail_mods=%d avg=%s"
              % (twin, n, net, w, pf, mods,
                 ("%+.2f" % (net / n)) if n else "n/a"))
        print("  pnls: " + " ".join("%+.0f" % t for t in trades))
    return 0


if __name__ == "__main__":
    sys.exit(main())
