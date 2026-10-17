"""Walk-forward validation for the swing strategy.

The single 200-day backtest in backtest_swing.py picked 'tight trail' on all
three timeframes, which is exactly the situation that produces an overfit
parameter set: three correlated timeframes over one contiguous window is ONE
sample, not three. This rolls independent windows and requires the chosen arm
to hold up in each, and reports the fixed-vs-trail edge per window so decay is
visible rather than averaged away.

Usage: python backtest_swing_walkforward.py [--days 400] [--window 30] [--step 10]
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from backtest_new_candidates import run
from backtest_swing import (BARS_PER_DAY, COST, DPU,
                            swing_events, set_trail)

# timeframes to roll (same set backtest_swing.py reports on)
BPD_UNIVERSE = ("M15", "M30", "H1")


def day_str(t):
    """The VPS MetaTrader5 build has no time_to_string(); format by hand."""
    return dt.datetime.utcfromtimestamp(int(t)).strftime("%Y-%m-%d")

TIGHT = (0.05, 0.15, 0.02)
LEGACY = (0.10, 0.30, 0.05)


def window_stats(bars, ev_all, t0, t1):
    """Run fixed vs tight-trail over signal bars whose CLOSE time falls in
    [t0,t1), reusing precomputed events.

    `ev_all` is passed in rather than recomputed because swing_events() is
    O(n^2) (it rebuilds the H1-bias EMA over a growing slice on every bar).
    Calling it once per window turned a ~1 minute backtest into a job that
    burnt 30 minutes of CPU without finishing. Indicators are warm and causal
    because the events were generated over the whole series up front; this
    only FILTERS them by timestamp, so no window sees future bars.
    """
    ev = [e for e in ev_all
          if t0 <= bars[e["sig_i"]]["time"] < t1]
    if not ev:
        return None
    # trim the bar series to the window so exits resolve inside it
    lo, hi = None, len(bars)
    for i, b in enumerate(bars):
        if b["time"] >= t0:
            lo = max(0, i - 1)
            break
    for i, b in enumerate(bars):
        if b["time"] >= t1:
            hi = i
            break
    if lo is None:
        return None
    win = bars[lo:hi]
    off = lo
    ev2 = []
    for e in ev:
        i = e["sig_i"] - off
        if 0 <= i < len(win) - 2:
            e2 = dict(e)
            e2["sig_i"] = i
            ev2.append(e2)
    if not ev2:
        return None
    fixed, _ = run(list(ev2), win, DPU, COST, None)
    set_trail(*TIGHT)
    tight, _m = run(list(ev2), win, DPU, COST, TIGHT)
    return fixed, tight


def summarise(trades):
    if not trades:
        return (0, 0.0, 0.0)
    return (len(trades), sum(trades), sum(trades) / len(trades))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--window", type=int, default=30, help="window days")
    ap.add_argument("--step", type=int, default=10, help="roll days")
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit("initialize failed: %r" % mt5.last_error())

    for tf in BPD_UNIVERSE:
        bpd = BARS_PER_DAY[tf]
        n = args.days * bpd
        rates = mt5.copy_rates_from_pos(
            args.symbol,
            {"M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
             "H1": mt5.TIMEFRAME_H1}[tf], 1, n)
        if rates is None or len(rates) == 0:
            continue
        bars = [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
                 "low": r["low"], "close": r["close"]} for r in rates]
        if not bars:
            continue
        span = bars[-1]["time"] - bars[0]["time"]
        day = 86400
        # compute the signal set ONCE for the whole series, then roll windows
        # over it (see window_stats docstring for why this must not be per-window)
        ev_all = swing_events(bars, bpd)
        print("\n" + "=" * 78)
        print("SWING WALK-FORWARD  %s  %d bars  %d signals  %dd span  "
              "%dd window / %dd roll"
              % (tf, len(bars), len(ev_all), span // day,
                 args.window, args.step), flush=True)
        print("=" * 78)
        print("%-12s %5s %5s %11s %11s %10s"
              % ("window", "n_f", "n_t", "fixed", "tight-trail", "edge/trip"))
        t_start = bars[0]["time"]
        t_end = bars[-1]["time"]
        wins = losses = 0
        rows = []
        t = t_start
        while t + args.window * day <= t_end:
            t0, t1 = t, t + args.window * day
            r = window_stats(bars, ev_all, t0, t1)
            if r:
                fixed, tight = r
                nf, sf, pf_ = summarise(fixed)
                nt, st, pt = summarise(tight)
                edge = pt - pf_
                rows.append((nf, sf, nt, st))
                if st > 0:
                    wins += 1
                else:
                    losses += 1
                print("%-12s %5d %5d %+11.2f %+11.2f %+10.2f"
                      % (day_str(t0), nf, nt, sf, st, edge), flush=True)
            t += args.step * day
        if not rows:
            print("  (no windows produced signals)")
            continue
        tot_f = sum(r[1] for r in rows)
        tot_t = sum(r[3] for r in rows)
        print("-" * 78)
        print("windows profitable (tight): %d/%d" % (wins, wins + losses))
        print("TOTAL fixed %+.2f   tight-trail %+.2f   edge %+.2f"
              % (tot_f, tot_t, tot_t - tot_f))
        print("verdict: %s" % ("ROBUST" if wins == wins + losses and tot_t > 0
                               else "DECAYS -- do not ship on this alone"))
    mt5.shutdown()


if __name__ == "__main__":
    main()