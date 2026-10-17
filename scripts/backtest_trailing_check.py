"""Full trailing-vs-fixed verdict matrix: ALL 7 strategies x 5 symbols, 30d M15.

Simulates every strategy's trades twice on identical data:
  fixed twin : static SL/TP, exits at SL or TP
  trail twin : the exact EA/runner trailing rule -- once unrealized gain
               >= 1.0*ATR, the stop ratchets to 1.2*ATR behind the best price
               (min step 0.3*ATR); exits at the ratcheted SL or the TP.
Pessimistic intrabar ordering: SL tested before TP; trail updates lag one bar.
Straddle/london: one stop-order fill per period, then the same exit rules.

Prints the matrix and a WINNER dict ready to paste into forward_test.py:
where trailing improved net profit, "trail" wins the slot; else "fixed".

Usage (VPS): python C:/FTTest/scripts/backtest_trailing_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import (LONDON_END_HOUR, LONDON_START_HOUR, atr, closed_bars,
                          strat_breakout, strat_london, strat_macross,
                          strat_meanrev, strat_smc, strat_squeeze,
                          strat_straddle)

# the LIVE twin rule since 9/28 (backtest_trail_sweep.py verdict: tight trail
# beat the old 1.0/1.2/0.3 baseline on 21 of 35 slots, +$407/30d aggregate)
TRAIL_ACTIVATE, TRAIL_DIST, TRAIL_STEP = 0.3, 0.7, 0.15
BARS_REQUEST = 30 * 96 + 300
SYMBOLS = ["XAUUSD"]   # XAU-only rig: FX retired from testing (2026-09-28)
SIGNAL_FNS = {"breakout": strat_breakout, "meanrev": strat_meanrev,
              "macross": strat_macross, "smc": strat_smc,
              "squeeze": strat_squeeze}
DUAL_MODES = {"straddle": "straddle", "london": "london"}


def walk_exit_fixed(side, sl, tp, bars, start_i):
    for j in range(start_i, len(bars)):
        b = bars[j]
        if side == "buy":
            if b["low"] <= sl:
                return sl, j
            if b["high"] >= tp:
                return tp, j
        else:
            if b["high"] >= sl:
                return sl, j
            if b["low"] <= tp:
                return tp, j
    return bars[-1]["close"], len(bars) - 1


def walk_exit_trail(side, entry, sl, tp, a, bars, start_i):
    """Static SL/TP until the trail activates, then the ratchet rule."""
    cur_sl, cur_tp = sl, tp
    mods = 0
    best = None
    for j in range(start_i, len(bars)):
        b = bars[j]
        # 1) pessimistic: today's SL test first (before any trail update)
        if side == "buy" and b["low"] <= cur_sl:
            return cur_sl, j, mods
        if side == "sell" and b["high"] >= cur_sl:
            return cur_sl, j, mods
        # 2) trail update from this bar's extreme (lags one bar: conservative)
        if side == "buy":
            if b["high"] - entry >= TRAIL_ACTIVATE * a:
                best = max(best, b["high"]) if best else b["high"]
                new_sl = best - TRAIL_DIST * a
                if new_sl > cur_sl + TRAIL_STEP * a:
                    cur_sl = new_sl
                    mods += 1
            if b["high"] >= cur_tp:
                return cur_tp, j, mods
        else:
            if entry - b["low"] >= TRAIL_ACTIVATE * a:
                best = min(best, b["low"]) if best else b["low"]
                new_sl = best + TRAIL_DIST * a
                if cur_sl == 0 or new_sl < cur_sl - TRAIL_STEP * a:
                    cur_sl = new_sl
                    mods += 1
            if b["low"] <= cur_tp:
                return cur_tp, j, mods
    return bars[-1]["close"], len(bars) - 1, mods


def run_signal(fn, bars, dpu, trailing):
    trades, mods_total = [], 0
    busy_until = -1
    for i in range(35, len(bars) - 2):
        if i <= busy_until:
            continue
        sig = fn(bars[max(0, i - 299):i + 1])
        if sig is None or sig[0] != "entry":
            continue
        side, sl, tp = sig[1], sig[2], sig[3]
        a = atr(bars[max(0, i - 299):i + 1])   # the ATR live trailing uses
        if not a:
            continue
        nxt = bars[i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or (side == "sell" and nxt["high"] >= sl):
            trades.append(0.0 if side == "buy" else (entry - sl) * dpu)
            trades[-1] = ((sl - entry) if side == "buy" else (entry - sl)) * dpu
            busy_until = i + 1
            continue
        if trailing:
            px, exit_i, m = walk_exit_trail(side, entry, sl, tp, a, bars, i + 2)
        else:
            px, exit_i = walk_exit_fixed(side, sl, tp, bars, i + 2)
            m = 0
        raw = (px - entry) if side == "buy" else (entry - px)
        trades.append(raw * dpu)
        mods_total += m
        busy_until = exit_i
    return trades, mods_total


def period_events(bars, session):
    """Yield (side, entry, sl, tp, fill_i, atr) -- one fill max per period."""
    idx = {b["time"]: i for i, b in enumerate(bars)}
    unit, sess_fn = ((86400, "london") if session == "london" else (3600, "straddle"))
    for p in sorted({b["time"] // unit for b in bars}):
        if session == "london":
            pbars = [b for b in bars if b["time"] // 86400 == p]
            window = [b for b in pbars
                      if LONDON_START_HOUR <= (b["time"] % 86400) // 3600 < LONDON_END_HOUR]
            if len(window) < 2:
                continue
            levels = strat_london(bars[:idx[window[0]["time"]] + 1])
        else:
            window = [b for b in bars if b["time"] // 3600 == p]
            if not window:
                continue
            levels = strat_straddle(bars[:idx[window[0]["time"]] + 1])
        if levels is None:
            continue
        bs, ss, a = levels["buy_stop"], levels["sell_stop"], levels["risk"]
        for b in window:
            i = idx[b["time"]]
            if b["high"] >= bs:
                yield "buy", bs, bs - a, bs + a, i, a
                break
            if b["low"] <= ss:
                yield "sell", ss, ss + a, ss - a, i, a
                break


def run_dual(bars, dpu, session, trailing):
    trades, mods_total = [], 0
    for side, entry, sl, tp, i, a in period_events(bars, session):
        b = bars[i]
        # same-bar SL after the trigger counts (pessimistic)
        if (side == "buy" and b["low"] <= sl) or (side == "sell" and b["high"] >= sl):
            px, mods = sl, 0
        elif trailing:
            px, _, mods = walk_exit_trail(side, entry, sl, tp, a, bars, i + 1)
        else:
            px, _ = walk_exit_fixed(side, sl, tp, bars, i + 1)
            mods = 0
        raw = (px - entry) if side == "buy" else (entry - px)
        trades.append(raw * dpu)
        mods_total += mods
    return trades, mods_total


def row(trades):
    if not trades:
        return (0, 0.0, "n/a")
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
    return (len(trades), sum(trades), pf)


def main():
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1

    verdicts = {}
    print("trailing rule: activate +%.1f ATR, trail %.1f ATR, step %.1f ATR (exact live values)" %
          (TRAIL_ACTIVATE, TRAIL_DIST, TRAIL_STEP))
    print("%-8s %-9s %18s %18s %6s %s" %
          ("SYMBOL", "STRATEGY", "FIXED n/net/PF", "TRAIL n/net/PF", "mods", "WINNER"))
    for s in SYMBOLS:
        mt5.symbol_select(s, True)
        si = mt5.symbol_info(s)
        if si is None:
            print("%-8s unavailable" % s)
            continue
        dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
        bars = closed_bars(s, "M15", BARS_REQUEST)
        if len(bars) < 400:
            print("%-8s not enough bars" % s)
            continue
        for name in list(SIGNAL_FNS) + list(DUAL_MODES):
            if name in SIGNAL_FNS:
                fixed, _ = run_signal(SIGNAL_FNS[name], bars, dpu, False)
                trail, mods = run_signal(SIGNAL_FNS[name], bars, dpu, True)
            else:
                fixed, _ = run_dual(bars, dpu, DUAL_MODES[name], False)
                trail, mods = run_dual(bars, dpu, DUAL_MODES[name], True)
            f, tr = row(fixed), row(trail)
            if f[0] == 0 and tr[0] == 0:
                continue  # no evidence either way: keep both variants live
            win = "trail" if tr[1] > f[1] else "fixed"
            verdicts[(s, name)] = win
            print("%-8s %-9s %4d %9.2f %5s %4d %9.2f %5s %6d %s"
                  % (s, name, f[0], f[1], f[2], tr[0], tr[1], tr[2], mods, win))
    mt5.shutdown()

    print()
    print("# paste into forward_test.py")
    print("WINNER = {")
    for (s, name) in sorted(verdicts):
        print('    ("%s", "%s"): "%s",' % (s, name, verdicts[(s, name)]))
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
