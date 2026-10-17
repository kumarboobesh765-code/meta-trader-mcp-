r"""Backtest the SuperTrend strategy on XAUUSD, fixed vs trailing twins.

Self-contained FAITHFUL Pine ta.supertrend port (2026-09-30). The shared
supertrend_dir() helper in backtest_new_candidates.py is BROKEN (direction
froze: 2759/2760 bars "up" while gold fell 4824->4160) -- all earlier sweep
numbers from it are garbage. This port flips on a close through the
RATCHETED band (canonical Pine); the frozen helper flipped on the FRESH band
(+ the AetherFlow branch-order bug), which a close can practically never
reach mid-trend.

House conventions: signals on the last CLOSED bar, entry at next bar open,
pessimistic same-bar SL on the entry bar, SL 2 x ATR(14) / TP 3 x ATR,
costs = spread (0.20) + $0.04/0.01-lot round trip, trail twin 0.3/0.7/0.15.

Usage: python backtest_supertrend.py [--days 30] [--period 10] [--factor 3.0]
                                     [--sweep] [--tf H1|M15]
"""
import argparse
import sys

sys.path.insert(0, "C:/FTTest/scripts")

from backtest_new_candidates import market_events, row, run
from backtest_aetherflow import sma_atr_at
import MetaTrader5 as mt5

from forward_test import closed_bars, load_env

BPD = {"H1": 24, "M15": 96}
FETCH_DAYS = 95


def rma(src, period):
    """Wilder RMA seeded with the SMA of the first `period` values
    (identical shape to AetherFlowEA CalcRMA so the EA port matches 1:1)."""
    n = len(src)
    p = min(period, n)
    seed = sum(src[:p]) / p
    out = [0.0] * n
    for i in range(n):
        out[i] = seed if i < period else (out[i - 1] * (period - 1) + src[i]) / period
    return out


def st_dir_pine(bars, period, factor):
    """Faithful Pine ta.supertrend port. dir: -1 = uptrend, +1 = downtrend.

      atr  = RMA(tr, period)          (Wilder, SMA-seeded)
      src  = (high + low) / 2
      up   = src + factor*atr ; dn = src - factor*atr
      bands ratchet against the previous FINAL band, reset when the PREV bar
      closed through the previous band:
        lb[i] = dn if (dn > lb[i-1] or close[i-1] < lb[i-1]) else lb[i-1]
        ub[i] = up if (up < ub[i-1] or close[i-1] > ub[i-1]) else ub[i-1]
      direction (Pine: -1 = up) flips ONLY on a close through the RATCHETED
      band matching the CURRENT state's own band:
        prev dir == +1 (downtrend, st = upper band):
            dir = close > ub[i] ? -1 : +1   (close punches the falling upper)
        prev dir == -1 (uptrend, st = lower band):
            dir = close < lb[i] ? +1 : -1   (close falls through rising lower)
    """
    n = len(bars)
    trs = []
    for i in range(n):
        if i == 0:
            trs.append(bars[i]["high"] - bars[i]["low"])
        else:
            pc = bars[i - 1]["close"]
            trs.append(max(bars[i]["high"] - bars[i]["low"],
                           abs(bars[i]["high"] - pc), abs(bars[i]["low"] - pc)))
    atr = rma(trs, period)

    dir_ = [0] * n
    ub = [0.0] * n
    lb = [0.0] * n
    st = [0.0] * n
    for i in range(n):
        src = (bars[i]["high"] + bars[i]["low"]) / 2.0
        up = src + factor * atr[i]
        dn = src - factor * atr[i]
        if i == 0:
            ub[i], lb[i], st[i], dir_[i] = up, dn, up, 1
            continue
        plb, pub = lb[i - 1], ub[i - 1]
        lb[i] = dn if (dn > plb or bars[i - 1]["close"] < plb) else plb
        ub[i] = up if (up < pub or bars[i - 1]["close"] > pub) else pub
        if dir_[i - 1] == 1:                       # was downtrend: st == ub
            dir_[i] = -1 if bars[i]["close"] > ub[i] else 1
        else:                                      # was uptrend: st == lb
            dir_[i] = 1 if bars[i]["close"] < lb[i] else -1
        st[i] = lb[i] if dir_[i] == -1 else ub[i]
    return dir_


def sig_supertrend(bars, trs, t0, period, factor):
    """Supertrend flip signals (period x factor) on closed bars.
    Flip to -1 (uptrend) -> buy, flip to +1 (downtrend) -> sell."""
    dir_ = st_dir_pine(bars, period, factor)
    out = []
    for i in range(1, len(bars)):
        if bars[i]["time"] < t0 or dir_[i] == dir_[i - 1] or i + 1 >= len(bars):
            continue
        a = sma_atr_at(trs, i, 14)
        if a and a > 0:
            out.append((i, "buy" if dir_[i] == -1 else "sell", a))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--period", type=int, default=10)
    ap.add_argument("--factor", type=float, default=3.0)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--tf", default="H1", choices=["H1", "M15"])
    args = ap.parse_args()

    load_env()
    import time as _t
    ok = False
    for attempt in range(5):
        if mt5.initialize():
            ok = True
            break
        print("attach attempt %d failed: %s -- retrying in 10s"
              % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        _t.sleep(10)
    if not ok:
        print("mt5.initialize() failed after 5 attempts")
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

    bars = closed_bars("XAUUSD", args.tf, FETCH_DAYS * BPD[args.tf] + 300)
    mt5.shutdown()
    if len(bars) < 600:
        print("not enough %s bars (%d)" % (args.tf, len(bars)))
        return 1
    series = bars  # naming kept for the shared runner below

    t0 = series[-1]["time"] - args.days * 86400
    # true TR series (first bar: full range)
    trs = []
    prev_close = None
    for b in series:
        pc = b["close"] if prev_close is None else prev_close
        trs.append(max(b["high"] - b["low"],
                       abs(b["high"] - pc), abs(b["low"] - pc)))
        prev_close = b["close"]

    ba_trail = __import__("backtest_aetherflow")
    ba_trail.TRAIL_ACTIVATE, ba_trail.TRAIL_DIST, ba_trail.TRAIL_STEP = 0.3, 0.7, 0.15

    if args.sweep:
        print("XAUUSD Supertrend sweep (FAITHFUL pine port) on %s: last %dd | "
              "SL 2 / TP 3 ATR | cost $%.2f/trade | trail 0.3/0.7/0.15"
              % (args.tf, args.days, cost))
        print("%-14s %6s   %20s   %20s"
              % ("(period,factor)", "flips", "FIXED n/net/PF", "TRAIL n/net/PF"))
        for period, factor in ((10, 3.0), (10, 2.0), (7, 2.0), (14, 3.0), (5, 2.0),
                               (10, 1.5), (7, 1.5), (14, 2.0)):
            dir_dbg = st_dir_pine(series, period, factor)
            flips = sum(1 for i in range(1, len(series))
                        if dir_dbg[i] != dir_dbg[i - 1])
            ups = sum(1 for d in dir_dbg if d == -1)
            sigs = sig_supertrend(series, trs, t0, period, factor)
            events = market_events(sigs, series)
            fixed, _ = run(events, series, dpu, cost, False)
            trail, _ = run(events, series, dpu, cost, True)
            f_n, f_net, f_pf, _ = row(fixed)
            t_n, t_net, t_pf, _ = row(trail)
            print("(%2d, %.1f)    %6d   %6d %+8.2f %-5s  %6d %+8.2f %-5s   [up%%=%.0f]"
                  % (period, factor, flips, f_n, f_net, f_pf, t_n, t_net, t_pf,
                     100.0 * ups / max(1, len(dir_dbg))))
        return 0

    sigs = sig_supertrend(series, trs, t0, args.period, args.factor)
    dir_dbg = st_dir_pine(series, args.period, args.factor)
    flips = sum(1 for i in range(1, len(series)) if dir_dbg[i] != dir_dbg[i - 1])
    print("debug: bars=%d total_flips=%d in-window_signals=%d"
          % (len(series), flips, len(sigs)))
    events = market_events(sigs, series)

    fixed, _ = run(events, series, dpu, cost, False)
    trail, mods = run(events, series, dpu, cost, True)
    f_n, f_net, f_pf, f_w = row(fixed)
    t_n, t_net, t_pf, t_w = row(trail)
    avg = (t_net / t_n) if t_n else 0.0

    print("XAUUSD Supertrend(%d, %.1f) on %s: last %dd traded of %dd data | "
          "SL 2 / TP 3 ATR | cost $%.2f/trade (0.01 lot) | trail 0.3/0.7/0.15"
          % (args.period, args.factor, args.tf, args.days, FETCH_DAYS, cost))
    print("%-8s %22s   %22s   %s"
          % ("TWIN", "FIXED n/net/PF/win%", "TRAIL n/net/PF/win%", "RANK"))
    print("%-8s %22s   %22s   %s"
          % ("supertrend",
             "%d/%+.2f/%s/%.0f%%" % (f_n, f_net, f_pf, f_w),
             "%d/%+.2f/%s/%.0f%%" % (t_n, t_net, t_pf, t_w),
             "avg/trade $%.2f | mods %d" % (avg, mods)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
