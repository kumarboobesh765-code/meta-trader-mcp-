"""Backtest ALL 7 FTTest strategies across multiple symbols, 30 days, and rank
by profit factor so we know which (if any) deserve to keep running.

Uses the REAL strategy functions from forward_test.py so results mirror live
logic. Pessimistic fill rules (same as backtest_london_squeeze.py):
  - stop orders fill only if the bar's high/low crosses the level
  - if SL and TP are both inside one bar, the SL is counted first
  - spread = current live spread x 1.5, charged once per round trip
  - commission 0.04 per round trip at 0.01 lot
  - signal entries fill at the next bar's open
  - signal strategies hold one position at a time (like the live runner)
  - straddle/london: one trade max per period (far side cancelled on fill)

P/L in dollars uses tick_value so forex pairs price correctly (gold works out
to 1.0 $/oz at 0.01 lot). Timeframe M15.

Usage (VPS): python C:/FTTest/scripts/backtest_all_7.py
"""

import os
import sys
import time as _time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import (LONDON_END_HOUR, LONDON_START_HOUR, closed_bars,
                          strat_breakout, strat_london, strat_macross,
                          strat_meanrev, strat_smc, strat_squeeze,
                          strat_straddle)

COMMISSION = 0.04            # round trip at 0.01 lot
BARS_REQUEST = 30 * 96 + 300  # ~30 days of M15 + warmup

SYMBOLS = ["XAUUSD"]   # XAU-only rig: FX retired from testing (2026-09-28)

STRAT_FNS = {
    "breakout": (strat_breakout, "signal"),
    "meanrev": (strat_meanrev, "signal"),
    "macross": (strat_macross, "signal"),
    "straddle": (strat_straddle, "straddle"),
    "smc": (strat_smc, "signal"),
    "london": (strat_london, "london"),
    "squeeze": (strat_squeeze, "signal"),
}

SPREAD = {}   # symbol -> pessimistic spread ($), filled in main()
DPU = {}      # symbol -> $ per 1.0 price move per 0.01 lot


def pnl(side, entry, exit_price, dpu, sym):
    raw = (exit_price - entry) if side == "buy" else (entry - exit_price)
    return raw * dpu - SPREAD[sym] - COMMISSION


def walk_to_exit(side, entry, sl, tp, bars, start_i):
    """Walk bars forward until SL or TP. SL wins ties (pessimistic).
    Returns (exit_price, bars_held); walks to the last bar if never hit."""
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


def bt_signal(fn, bars, dpu, sym):
    """Signal-strategy sim: evaluate each closed bar, enter next bar's open.
    One position at a time (mirrors the live runner)."""
    trades = []
    busy_until = -1
    for i in range(35, len(bars) - 2):
        if i <= busy_until:
            continue
        sig = fn(bars[max(0, i - 299):i + 1])   # live passes a 300-bar window
        if sig is None or sig[0] != "entry":
            continue
        side, sl, tp = sig[1], sig[2], sig[3]
        nxt = bars[i + 1]
        entry = nxt["open"]
        # same-bar exit at the entry bar: SL first (pessimistic), then TP
        if (side == "buy" and nxt["low"] <= sl) or (side == "sell" and nxt["high"] >= sl):
            trades.append(pnl(side, entry, sl, dpu, sym))
            busy_until = i + 1
            continue
        if (side == "buy" and nxt["high"] >= tp) or (side == "sell" and nxt["low"] <= tp):
            trades.append(pnl(side, entry, tp, dpu, sym))
            busy_until = i + 1
            continue
        x, held = walk_to_exit(side, entry, sl, tp, bars, i + 2)
        trades.append(pnl(side, entry, x, dpu, sym))
        busy_until = i + 1 + held
    return trades


def bt_period(bars, dpu, sym, session):
    """Dual-stop sim, one trade max per period.
    session='straddle': one period = one H1 bar; levels = last-4-closed-bar
    range (computed at the period's first bar, like the runner).
    session='london': one period = one day; Asian-range levels at the London
    open; orders live only during the London window."""
    idx = {b["time"]: i for i, b in enumerate(bars)}
    trades = []
    if session == "london":
        periods = sorted({b["time"] // 86400 for b in bars})
    else:
        periods = sorted({b["time"] // 3600 for b in bars})

    for p in periods:
        if session == "london":
            pbars = [b for b in bars if b["time"] // 86400 == p]
            window = [b for b in pbars
                      if LONDON_START_HOUR <= (b["time"] % 86400) // 3600 < LONDON_END_HOUR]
            if len(window) < 2:
                continue
            end_bar = window[0]
            levels = strat_london(bars[:idx[end_bar["time"]] + 1])
        else:
            window = [b for b in bars if b["time"] // 3600 == p]
            if not window:
                continue
            end_bar = window[0]
            levels = strat_straddle(bars[:idx[end_bar["time"]] + 1])
        if levels is None:
            continue
        buy_stop, sell_stop, a = levels["buy_stop"], levels["sell_stop"], levels["risk"]

        for b in window:
            i = idx[b["time"]]
            if b["high"] >= buy_stop:
                side, entry, sl, tp = "buy", buy_stop, buy_stop - a, buy_stop + a
            elif b["low"] <= sell_stop:
                side, entry, sl, tp = "sell", sell_stop, sell_stop + a, sell_stop - a
            else:
                continue
            # same-bar SL after the trigger counts (pessimistic); TP does not
            if (side == "buy" and b["low"] <= sl) or \
               (side == "sell" and b["high"] >= sl):
                trades.append(pnl(side, entry, sl, dpu, sym))
            else:
                x, _ = walk_to_exit(side, entry, sl, tp, bars, i + 1)
                trades.append(pnl(side, entry, x, dpu, sym))
            break   # one trade max per period (far side cancelled on fill)
    return trades


def row(name, trades):
    if not trades:
        return (name, 0, 0.0, "n/a", -1.0, 0.0)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))
    pf = (gross_w / gross_l) if gross_l > 0 else 999.0   # 999 prints as "inf"
    eq = peak = dd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return (name, len(trades), sum(trades),
            "inf" if pf == 999.0 else "%.2f" % pf, pf, dd)


def main():
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1

    for s in SYMBOLS:
        mt5.symbol_select(s, True)
        si = mt5.symbol_info(s)
        t = mt5.symbol_info_tick(s)
        if si is None or t is None:
            print("symbol unavailable: %s" % s)
            mt5.shutdown()
            return 1
        SPREAD[s] = (t.ask - t.bid) * 1.5   # pessimistic spread
        # raw-spread feeds can quote ~0 pips live; floor FX at 1 pip so the
        # pessimistic assumption stays real (gold keeps its measured spread)
        if s != "XAUUSD" and SPREAD[s] < 0.00010:
            SPREAD[s] = 0.00010
        DPU[s] = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01

    print("pessimistic fills: spread=live x1.5 (FX floor 1 pip), comm $0.04/RT, SL-first intrabar")
    print("%-8s %12s %12s" % ("SYMBOL", "SPREAD$", "$/1.0move"))
    for s in SYMBOLS:
        print("%-8s %12.5f %12.4f" % (s, SPREAD[s], DPU[s]))
    print()

    results = {s: {} for s in SYMBOLS}
    t0 = _time.time()
    for s in SYMBOLS:
        bars = closed_bars(s, "M15", BARS_REQUEST)
        if len(bars) < 400:
            print("%-8s not enough bars (%d)" % (s, len(bars)))
            continue
        span = (bars[-1]["time"] - bars[0]["time"]) / 86400.0
        print("%-8s %d bars (%.1f days) ..." % (s, len(bars), span), flush=True)
        for name, (fn, mode) in STRAT_FNS.items():
            if mode == "signal":
                tr = bt_signal(fn, bars, DPU[s], s)
            elif mode == "straddle":
                tr = bt_period(bars, DPU[s], s, "straddle")
            else:
                tr = bt_period(bars, DPU[s], s, "london")
            results[s][name] = tr
    print("(sim took %.0fs)" % (_time.time() - t0))

    # ranked table: every symbol x strategy
    rows = []
    for s in SYMBOLS:
        for name in STRAT_FNS:
            _, n, net, pfs, pfkey, dd = row(name, results[s].get(name, []))
            rows.append((s, name, n, net, pfs, pfkey, dd))
    print()
    print("%-8s %-9s %6s %9s %6s %8s" % ("SYMBOL", "STRATEGY", "TRADES", "NET$", "PF", "MAXDD$"))
    for r in sorted(rows, key=lambda r: (-r[5], -r[3])):
        print("%-8s %-9s %6d %9.2f %6s %8.2f" % (r[0], r[1], r[2], r[3], r[4], r[6]))

    # per-strategy totals across all symbols
    print()
    print("PER-STRATEGY TOTALS (all 5 symbols combined)")
    print("%-9s %6s %9s %6s %8s" % ("STRATEGY", "TRADES", "NET$", "PF", "MAXDD$"))
    ranked = []
    for name in STRAT_FNS:
        all_tr = []
        for s in SYMBOLS:
            all_tr.extend(results[s].get(name, []))
        _, n, net, pfs, pfkey, dd = row(name, all_tr)
        ranked.append((name, n, net, pfs, dd, pfkey))
    for r in sorted(ranked, key=lambda r: (-r[5], -r[2])):
        print("%-9s %6d %9.2f %6s %8.2f" % (r[0], r[1], r[2], r[3], r[4]))

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
