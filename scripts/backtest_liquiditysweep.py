r"""Backtest the LiquiditySweep strategy on XAUUSD H4 (port spec for
FT_LIQUIDITYSWEEP). Companion to the binary 'liquiditySweep Best H4.ex5'
(chart37 A/B).

House conventions: closed-bar signal, entry NEXT bar via stop order at the
reclaim level, pessimistic same-bar SL, SL 1.5 x ATR(14) / TP 3 x ATR,
one trade per 4h bar, cost $0.24/trade (0.01 lot).

Usage: python backtest_liquiditysweep.py [--sweep] [--days 30]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from backtest_aetherflow import sma_atr_at, tr_series, walk_exit_fixed, walk_exit_trail
from forward_test import closed_bars, load_env

FETCH_DAYS = 100
BPD = 6


def sweep_signals(bars, trs, lookback, wick_ratio, buf_atr, t0,
                  require_dir=False):
    """Sweep-and-reclaim events per H4 bar. Returns list of
    (sig_i, side, trigger, a). require_dir=False lets the sweep candle close
    either way as long as it reclaimed the level (looser, more signals)."""
    out = []
    for i in range(max(lookback + 2, 30), len(bars)):
        if bars[i]["time"] < t0:
            continue
        a = sma_atr_at(trs, i, 14)
        if not a or a <= 0:
            continue
        b = bars[i]
        rng = b["high"] - b["low"]
        if rng <= 0:
            continue
        lw = min(b["open"], b["close"]) - b["low"]
        uw = b["high"] - max(b["open"], b["close"])
        # prior window extremes EXCLUDING the signal bar itself
        lo = min(bb["low"] for bb in bars[i - lookback:i])
        hi = max(bb["high"] for bb in bars[i - lookback:i])
        # bullish: sweeps the low by wick, closes back above it; trigger =
        # reclaim of the swept low
        if (b["low"] < lo and b["close"] > lo + buf_atr * a
                and lw >= wick_ratio * rng
                and (b["close"] > b["open"] or not require_dir)):
            out.append((i, "buy", lo, a))
        # bearish: spikes the high by wick, closes back below it; trigger =
        # reclaim of the swept high
        elif (b["high"] > hi and b["close"] < hi - buf_atr * a
              and uw >= wick_ratio * rng
              and (b["close"] < b["open"] or not require_dir)):
            out.append((i, "sell", hi, a))
    return out


def run_strategy(bars, trs, dpu, cost, sigs, trailing):
    """Stop-order entry at the trigger on the next bar; ATR stop/target;
    one trade per signal bar."""
    trades = []
    for i, side, trig, a in sigs:
        if i + 1 >= len(bars):
            break
        nb = bars[i + 1]
        entry = trig
        if side == "buy":
            if nb["low"] > trig:      # never pulled back to the level
                continue
            if nb["low"] <= entry - 1.5 * a:      # pessimistic same-bar SL
                trades.append(-1.5 * a * dpu - cost)
                continue
            px, j = walk_exit_fixed("buy", entry - 1.5 * a,
                                    entry + 3 * a, bars, i + 1)
            px, j, _ = walk_exit_trail("buy", entry, entry - 1.5 * a,
                                       entry + 3 * a, a, bars, i + 1) \
                if trailing else (px, j, 0)
            trades.append((px - entry) * dpu - cost)
        else:
            if nb["high"] < trig:
                continue
            if nb["high"] >= entry + 1.5 * a:
                trades.append(-1.5 * a * dpu - cost)
                continue
            px, j = walk_exit_fixed("sell", entry + 1.5 * a,
                                    entry - 3 * a, bars, i + 1)
            px, j, _ = walk_exit_trail("sell", entry, entry + 1.5 * a,
                                       entry - 3 * a, a, bars, i + 1) \
                if trailing else (px, j, 0)
            trades.append((entry - px) * dpu - cost)
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

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
        return 3
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        return 2
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    bars = closed_bars("XAUUSD", "H4", FETCH_DAYS * BPD + 300)
    mt5.shutdown()
    trs = tr_series(bars)
    t0 = bars[-1]["time"] - args.days * 86400

    if args.sweep:
        print("XAUUSD LiquiditySweep H4: last %dd | SL 1.5 / TP 3 ATR | "
              "cost $%.2f" % (args.days, cost))
        print("%-22s %20s %20s" % ("(lookback,wick,buf)", "FIXED n/net", "TRAIL n/net"))
        best = None
        for lookback, wick, buf, rdir in ((20, 0.3, 0.05, True),
                                          (48, 0.3, 0.05, True),
                                          (48, 0.2, 0.05, False),
                                          (48, 0.15, 0.1, False),
                                          (96, 0.2, 0.05, False),
                                          (96, 0.15, 0.1, False),
                                          (96, 0.25, 0.05, False),
                                          (96, 0.2, 0.15, False)):
            sigs = sweep_signals(bars, trs, lookback, wick, buf, t0, rdir)
            f = run_strategy(bars, trs, dpu, cost, sigs, False)
            t = run_strategy(bars, trs, dpu, cost, sigs, True)
            fn, fnet = len(f), sum(f)
            tn, tnet = len(t), sum(t)
            print("(%3d, %.2f, %.2f, dir=%d) %10d %+9.2f %14d %+9.2f"
                  % (lookback, wick, buf, rdir, fn, fnet, tn, tnet))
            score = max(fnet, tnet)
            if best is None or score > best[0]:
                best = (score, lookback, wick, buf, rdir)
        print("best:", best)
        return 0

    sigs = sweep_signals(bars, trs, 30, 0.3, 0.05, t0)
    f = run_strategy(bars, trs, dpu, cost, sigs, False)
    t = run_strategy(bars, trs, dpu, cost, sigs, True)
    print("default (30, 0.30, 0.05): fixed n=%d net=%+.2f | trail n=%d net=%+.2f"
          % (len(f), sum(f), len(t), sum(t)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
