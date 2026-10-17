"""Backtest london + squeeze on the last 30 days of XAUUSD M15 bars.

Uses the REAL strategy functions from forward_test.py (strat_london,
strat_squeeze) so the numbers mirror what the live runner will actually do.
Fill assumptions are deliberately pessimistic:
  - stop orders fill only if the bar's high/low crosses the level
  - if SL and TP are both inside one bar, the SL is counted first
  - spread 0.10 + commission 0.04 per round trip (live demo: 0.07-0.12, 0.04)
  - signal entries fill at the next bar's open (runner acts within 30s)
  - london: orders only during the London session window, one trade max/day,
    unfilled orders die at session end (mirrors the live ttl/cancel behavior)

Runs on the VPS (has MT5 + data). Output is a plain stats table.

Usage (VPS): python C:/FTTest/scripts/backtest_london_squeeze.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import (LONDON_END_HOUR, LONDON_START_HOUR, closed_bars,
                          strat_london, strat_squeeze)

SPREAD = 0.10     # round trip, $/oz (=> $1 per 0.01 lot per $0.10 of spread)
COMMISSION = 0.04  # round trip at 0.01 lot (deals.csv shows 0.02 per side)


def walk_to_exit(side, entry, sl, tp, bars, start_i):
    """Walk bars forward until SL or TP. SL wins ties (pessimistic).
    Returns (exit_price, bars_held). Walks to the last bar if never hit."""
    for j in range(start_i, len(bars)):
        b = bars[j]
        if side == "buy":
            if b["low"] <= sl:
                return sl, j - start_i + 1
            if b["high"] >= tp:
                return tp, j - start_i + 1
        else:
            if b["high"] >= sl:
                return sl, j - start_i + 1
            if b["low"] <= tp:
                return tp, j - start_i + 1
    return bars[-1]["close"], len(bars) - start_i


def pnl(side, entry, exit_price):
    raw = (exit_price - entry) if side == "buy" else (entry - exit_price)
    return raw - SPREAD - COMMISSION   # XAUUSD: $1 price move = $1 at 0.01 lot


def stats(name, trades):
    if not trades:
        print("%-8s no trades in 30d" % name)
        return
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    total = sum(trades)
    eq = peak = maxdd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    gross_w, gross_l = sum(wins), abs(sum(losses))
    pf = ("%.2f" % (gross_w / gross_l)) if gross_l > 0 else "inf"
    print("%-8s trades=%-3d win%%=%-5.1f net=$%-8.2f avg=$%-6.2f "
          "best=$%-6.2f worst=$%-7.2f PF=%-5s maxDD=$%.2f"
          % (name, len(trades), 100.0 * len(wins) / len(trades), total,
             total / len(trades), max(wins) if wins else 0.0,
             min(losses) if losses else 0.0, pf, maxdd))


def bt_london(bars):
    """Once per day: stop orders around the Asian range at the London open."""
    idx = {b["time"]: i for i, b in enumerate(bars)}
    trades = []
    days = sorted({b["time"] // 86400 for b in bars})
    for day in days:
        dbars = [b for b in bars if b["time"] // 86400 == day]
        sess = [b for b in dbars
                if LONDON_START_HOUR <= (b["time"] % 86400) // 3600 < LONDON_END_HOUR]
        if len(sess) < 2:
            continue
        # the runner computes levels from history ending at the session's first bar
        levels = strat_london(bars[:idx[sess[0]["time"]] + 1])
        if levels is None:
            continue
        buy_stop, sell_stop, a = levels["buy_stop"], levels["sell_stop"], levels["risk"]
        filled = None
        for b in sess:
            i = idx[b["time"]]
            if b["high"] >= buy_stop:      # buy checked first on same-bar both-touch
                filled = ("buy", buy_stop, buy_stop - a, buy_stop + a, i)
            elif b["low"] <= sell_stop:
                filled = ("sell", sell_stop, sell_stop + a, sell_stop - a, i)
            if filled:
                side, entry, sl, tp, fi = filled
                # same-bar SL after trigger counts (pessimistic); TP does not
                if (side == "buy" and b["low"] <= sl) or \
                   (side == "sell" and b["high"] >= sl):
                    trades.append(pnl(side, entry, sl))
                else:
                    x, _ = walk_to_exit(side, entry, sl, tp, bars, fi + 1)
                    trades.append(pnl(side, entry, x))
                break   # one trade max per day (far side cancelled on fill)
    return trades


def bt_signal(fn, bars):
    """Signal-strategy sim: evaluate each closed bar, enter next bar's open.
    One position at a time (mirrors the live runner)."""
    trades = []
    busy_until = -1
    for i in range(35, len(bars) - 2):
        if i <= busy_until:
            continue
        # live passes a rolling 300-bar window; mirror that exactly
        sig = fn(bars[max(0, i - 299):i + 1])
        if sig is None or sig[0] != "entry":
            continue
        side, sl, tp = sig[1], sig[2], sig[3]
        nxt = bars[i + 1]
        entry = nxt["open"]
        # same-bar exit at the entry bar: SL first (pessimistic), then TP
        if (side == "buy" and nxt["low"] <= sl) or (side == "sell" and nxt["high"] >= sl):
            trades.append(pnl(side, entry, sl))
            busy_until = i + 1
            continue
        if (side == "buy" and nxt["high"] >= tp) or (side == "sell" and nxt["low"] <= tp):
            trades.append(pnl(side, entry, tp))
            busy_until = i + 1
            continue
        x, held = walk_to_exit(side, entry, sl, tp, bars, i + 2)
        trades.append(pnl(side, entry, x))
        busy_until = i + 1 + held
    return trades


def main():
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    symbol = "XAUUSD"
    mt5.symbol_select(symbol, True)
    bars = closed_bars(symbol, "M15", 30 * 96 + 300)
    if len(bars) < 500:
        print("not enough bars: %d" % len(bars))
        mt5.shutdown()
        return 1
    span_days = (bars[-1]["time"] - bars[0]["time"]) / 86400.0
    print("XAUUSD M15, last %.1f days (%d bars), pessimistic fills "
          "(spread %.2f + comm %.2f per RT, SL-first intrabar)" %
          (span_days, len(bars), SPREAD, COMMISSION))
    print()
    stats("london", bt_london(bars))
    stats("squeeze", bt_signal(strat_squeeze, bars))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
