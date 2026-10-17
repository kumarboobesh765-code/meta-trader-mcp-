r"""Backtest the AetherFlow EA logic (AETHER FLOW SYSTEM, Mxwll Fusion port).

A faithful port of mql5/AetherFlowEA.mq5 to bar-replay (same harness rules as
backtest_trailing_check.py / backtest_smvp.py):
  - signals evaluated on each CLOSED M15 bar; entry at the NEXT bar's open
  - UT Bot: exact Pine state machine (Key Value x Wilder-ATR trailing stop,
    ATR period 6), events = crossovers of src vs stop
  - SMC structure: externals (sens 25) + internals (sens 5) with CHoCH/BoS
    classification and the upside/downside liquidity arming
  - Three-Bar Reversal: detection + confirmation state machine (trend filter
    disabled by default, TrendType NONE)
  - Reversal Signals: 9-period momentum count flags (soft confluence module)
  - Hull Suite: HMA(55) trend color for the optional InpUseHullFilter
  - confluence mode: score >= 3, strict majority, at least one "hard" module
    (FVG/OB retests omitted: their confluence inputs default OFF and the
     zone counts never affect any trade decision)
  - SL/TP = close +/- 2/3 x SMA-ATR(14) at signal time (the EA's CalcATR)
  - twins: fixed (static SL/TP) vs trailing (activate +1.0 ATR, distance
    1.2 ATR, step 0.3 ATR -- the EA's -T twin defaults, exact FTTest rule);
    pessimistic intrabar ordering: SL tested before trail updates
  - costs per round trip: broker spread (below) + $0.04 commission at 0.01 lot
  - one position at a time; the EA would reverse on an opposite signal, the
    harness (like all our backtests) stays in the trade until SL/TP instead

Usage (VPS): python C:/FTTest/scripts/backtest_aetherflow.py
            [--symbol XAUUSD] [--tf M15|M30|H1] [--days 30]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import closed_bars

BARS_PER_DAY = {"M15": 96, "M30": 48, "H1": 24}
SYMBOLS = ["XAUUSD"]   # XAU-only rig: FX retired from testing (2026-09-28)
TF = "M15"
DAYS = 30
BARS_REQUEST = DAYS * BARS_PER_DAY[TF] + 300
TRAIL_ACTIVATE, TRAIL_DIST, TRAIL_STEP = 1.0, 1.2, 0.3
SL_ATR_MULT, TP_ATR_MULT = 2.0, 3.0
COMMISSION = 0.04
SPREAD_PRICE = {"XAUUSD": 0.20, "EURUSD": 0.00015, "GBPUSD": 0.00020,
                "USDJPY": 0.015, "AUDUSD": 0.00020}
UT_KEY, UT_ATR_PERIOD = 2.0, 6
EXT_SENS, INT_SENS = 25, 5
MIN_CONFLUENCE = 3
WARMUP = 60   # covers ext sens 25 + momentum lookback + ATR windows


# ---------------------------------------------------------------- series math

def tr_series(bars):
    out = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b["high"] - b["low"])
        else:
            pc = bars[i - 1]["close"]
            out.append(max(b["high"] - b["low"],
                           abs(b["high"] - pc), abs(b["low"] - pc)))
    return out


def sma_atr_at(trs, i, period=14):
    if i < period:
        return None
    return sum(trs[i - period + 1:i + 1]) / period


def wilder_atr_series(trs, period):
    out = [0.0] * len(trs)
    a = trs[0]
    for i, tr in enumerate(trs):
        a = tr if i == 0 else (a * (period - 1) + tr) / period
        out[i] = a
    return out


def wma_series(src, period):
    n = len(src)
    out = list(src)
    if period < 1:
        period = 1
    denom = period * (period + 1) / 2.0
    for i in range(period - 1, n):
        s = 0.0
        for k in range(period):
            s += src[i - k] * (period - k)
        out[i] = s / denom
    return out


def hull_up_series(bars, length=55):
    closes = [b["close"] for b in bars]
    a = wma_series(closes, max(1, length // 2))
    b = wma_series(closes, max(2, length))
    d = [2 * a[i] - b[i] for i in range(len(bars))]
    h = wma_series(d, max(1, int(round(length ** 0.5))))
    return [False] * 2 + [h[i] > h[i - 2] for i in range(2, len(bars))]


# ------------------------------------------------------------------- engines

def ut_bot_series(bars):
    """Exact StepUT port; returns (buy[], sell[], pos[])."""
    trs = tr_series(bars)
    atrs = wilder_atr_series(trs, UT_ATR_PERIOD)
    n = len(bars)
    buy = [False] * n
    sell = [False] * n
    pos = [0] * n
    stop = 0.0
    src_prev = 0.0
    p = 0
    for i in range(n):
        src = bars[i]["close"]
        nloss = UT_KEY * atrs[i]
        prev_stop, prev_src = stop, src_prev
        if i == 0:
            stop = src - nloss
        else:
            if src > prev_stop and prev_src > prev_stop:
                stop = max(prev_stop, src - nloss)
            elif src < prev_stop and prev_src < prev_stop:
                stop = min(prev_stop, src + nloss)
            elif src > prev_stop:
                stop = src - nloss
            else:
                stop = src + nloss
            if prev_src < prev_stop and src > prev_stop:
                p = 1
            elif prev_src > prev_stop and src < prev_stop:
                p = -1
        buy[i] = (src > stop) and (prev_src <= prev_stop)
        sell[i] = (stop > src) and (prev_stop <= prev_src)
        pos[i] = p
        src_prev = src
    return buy, sell, pos


def structure_events(bars, S):
    """Exact StepStructure port; returns (bull_ev[], bear_ev[], kind arrays)."""
    n = len(bars)
    bull = [0] * n
    bear = [0] * n
    kind_b = [0] * n
    kind_s = [0] * n
    intra = 0
    upside = downside = 1
    up_axis = dn_axis = 0.0
    moving = 0
    for i in range(n):
        if i < S:
            continue
        prev_intra = intra
        c_hi, c_lo = bars[i - S]["high"], bars[i - S]["low"]
        max_recent = max(b["high"] for b in bars[i - S + 1:i + 1])
        min_recent = min(b["low"] for b in bars[i - S + 1:i + 1])
        if c_hi > max_recent:
            intra = 0
        elif c_lo < min_recent:
            intra = 1
        if intra == 0 and prev_intra != 0:
            upside = 1
            up_axis = c_hi
        if intra == 1 and prev_intra != 1:
            downside = 1
            dn_axis = c_lo
        cl, cl1 = bars[i]["close"], bars[i - 1]["close"]
        if up_axis > 0 and cl > up_axis and cl1 <= up_axis and upside != 0:
            bull[i] = 1
            kind_b[i] = 1 if moving < 0 else 2
            upside = 0
            moving = 1
        if dn_axis > 0 and cl < dn_axis and cl1 >= dn_axis and downside != 0:
            bear[i] = 1
            kind_s[i] = 1 if moving > 0 else 2
            downside = 0
            moving = -1
    return bull, bear, kind_b, kind_s


def three_bar_reversal(bars):
    """Step3BR port with the default trend filter (NONE -> both trends on)."""
    n = len(bars)
    ev_b = [False] * n
    ev_s = [False] * n
    cf_b = [False] * n
    cf_s = [False] * n
    proc_b = proc_s = False
    at = ab = st = sb = 0.0
    for i in range(2, n):
        c0, c1, c2 = bars[i], bars[i - 1], bars[i - 2]
        bull_pat = (c2["close"] < c2["open"]) and (c1["low"] < c2["low"]) and \
                   (c1["high"] < c2["high"]) and (c1["close"] < c1["open"]) and \
                   (c0["close"] > c0["open"]) and (c0["high"] > c2["high"])
        bear_pat = (c2["close"] > c2["open"]) and (c1["high"] > c2["high"]) and \
                   (c1["low"] > c2["low"]) and (c1["close"] > c1["open"]) and \
                   (c0["close"] < c0["open"]) and (c0["low"] < c2["low"])
        if bull_pat:
            proc_b, ev_b[i] = True, True
            at = c2["high"]
            ab = min(c1["low"], c0["low"])
        if proc_b:
            if c1["close"] > at:
                cf_b[i], proc_b = True, False
            elif c1["close"] < ab or bear_pat:
                proc_b = False
        if bear_pat:
            proc_s, ev_s[i] = True, True
            sb = c2["low"]
            st = max(c1["high"], c0["high"])
        if proc_s:
            if c1["close"] > st or bull_pat:
                proc_s = False
            elif c1["close"] < sb:
                cf_s[i], proc_s = True, False
    return ev_b, ev_s, cf_b, cf_s


def momentum_flags(bars):
    """StepRS port: 9-period momentum count flags."""
    n = len(bars)
    bull = [False] * n
    bear = [False] * n
    b_cnt = s_cnt = 0
    for i in range(4, n):
        if bars[i]["close"] < bars[i - 4]["close"]:
            b_cnt = 1 if b_cnt == 9 else b_cnt + 1
            s_cnt = 0
        else:
            s_cnt = 1 if s_cnt == 9 else s_cnt + 1
            b_cnt = 0
        bull[i] = (b_cnt == 9)
        bear[i] = (s_cnt == 9)
    return bull, bear


# ------------------------------------------------------------------ exits

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
    cur_sl = sl
    best = None
    mods = 0
    for j in range(start_i, len(bars)):
        b = bars[j]
        if side == "buy" and b["low"] <= cur_sl:
            return cur_sl, j, mods
        if side == "sell" and b["high"] >= cur_sl:
            return cur_sl, j, mods
        if side == "buy":
            if b["high"] - entry >= TRAIL_ACTIVATE * a:
                best = max(best, b["high"]) if best else b["high"]
                new_sl = best - TRAIL_DIST * a
                if new_sl > cur_sl + TRAIL_STEP * a:
                    cur_sl = new_sl
                    mods += 1
            if b["high"] >= tp:
                return tp, j, mods
        else:
            if entry - b["low"] >= TRAIL_ACTIVATE * a:
                best = min(best, b["low"]) if best else b["low"]
                new_sl = best + TRAIL_DIST * a
                if cur_sl == 0 or new_sl < cur_sl - TRAIL_STEP * a:
                    cur_sl = new_sl
                    mods += 1
            if b["low"] <= tp:
                return tp, j, mods
    return bars[-1]["close"], len(bars) - 1, mods


# ------------------------------------------------------------------ signals

class Engines:
    def __init__(self, bars):
        self.bars = bars
        self.n = len(bars)
        self.ut_buy, self.ut_sell, self.ut_pos = ut_bot_series(bars)
        self.ext_b, self.ext_s, self.ext_kb, self.ext_ks = \
            structure_events(bars, EXT_SENS)
        self.int_b, self.int_s, _, _ = structure_events(bars, INT_SENS)
        self.b3ev, self.s3ev, self.b3cf, self.s3cf = three_bar_reversal(bars)
        self.mom_b, self.mom_s = momentum_flags(bars)
        self.hull_up = hull_up_series(bars)
        self.trs = tr_series(bars)

    def confluence(self, i):
        bull = bear = bull_hard = bear_hard = 0
        if self.ut_buy[i]:
            bull, bull_hard = bull + 1, bull_hard + 1
        if self.ut_sell[i]:
            bear, bear_hard = bear + 1, bear_hard + 1
        if self.ext_b[i]:
            bull, bull_hard = bull + 1, bull_hard + 1
        if self.ext_s[i]:
            bear, bear_hard = bear + 1, bear_hard + 1
        if self.int_b[i]:
            bull += 1
        if self.int_s[i]:
            bear += 1
        if self.b3ev[i] or self.b3cf[i]:
            bull, bull_hard = bull + 1, bull_hard + 1
        if self.s3ev[i] or self.s3cf[i]:
            bear, bear_hard = bear + 1, bear_hard + 1
        if self.mom_b[i]:
            bull += 1
        if self.mom_s[i]:
            bear += 1
        want_buy = bull >= MIN_CONFLUENCE and bull > bear and bull_hard > 0
        want_sell = bear >= MIN_CONFLUENCE and bear > bull and bear_hard > 0
        return want_buy, want_sell


def run_backtest(eng, bars, dpu, cost, mode, trailing, use_hull_filter):
    trades, mods_total = [], 0
    busy_until = -1
    for i in range(WARMUP, eng.n - 2):
        if i <= busy_until:
            continue
        if mode == "ut":
            want_buy, want_sell = eng.ut_buy[i], eng.ut_sell[i]
        else:
            want_buy, want_sell = eng.confluence(i)
        if not want_buy and not want_sell:
            continue
        if use_hull_filter:
            if want_buy and not eng.hull_up[i]:
                continue
            if want_sell and eng.hull_up[i]:
                continue
        if want_buy and want_sell:
            continue
        side = "buy" if want_buy else "sell"
        a = sma_atr_at(eng.trs, i)
        if not a:
            continue
        px = bars[i]["close"]
        sl = px - SL_ATR_MULT * a if side == "buy" else px + SL_ATR_MULT * a
        tp = px + TP_ATR_MULT * a if side == "buy" else px - TP_ATR_MULT * a
        nxt = bars[i + 1]
        entry = nxt["open"]
        # same-bar SL after entry (pessimistic)
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            trades.append(raw * dpu - cost)
            busy_until = i + 1
            continue
        if trailing:
            exit_px, exit_i, m = walk_exit_trail(side, entry, sl, tp, a,
                                                 bars, i + 2)
        else:
            exit_px, exit_i = walk_exit_fixed(side, sl, tp, bars, i + 2)
            m = 0
        raw = (exit_px - entry) if side == "buy" else (entry - exit_px)
        trades.append(raw * dpu - cost)
        mods_total += m
        busy_until = exit_i
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
    global SYMBOLS, TF, DAYS, BARS_REQUEST
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None,
                    help="single symbol (default: all five pairs)")
    ap.add_argument("--tf", default="M15", choices=sorted(BARS_PER_DAY))
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    if args.symbol:
        SYMBOLS = [args.symbol]
    TF = args.tf
    DAYS = args.days
    BARS_REQUEST = DAYS * BARS_PER_DAY[TF] + 300

    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    print("account %s %s (demo ok)" % (acc.login, acc.server))
    print("aetherflow port [%s, %dd]: UT key=%.1f atr=%d | SL %.0f ATR / "
          "TP %.0f ATR | costs = spread + $0.04 | twins fixed vs "
          "trail(1.0/1.2/0.3)"
          % (TF, DAYS, UT_KEY, UT_ATR_PERIOD, SL_ATR_MULT, TP_ATR_MULT))
    print("%-8s %-11s %20s %20s %s" %
          ("SYMBOL", "MODE", "FIXED n/net/PF", "TRAIL n/net/PF", "WINNER"))
    verdicts = {}
    for s in SYMBOLS:
        mt5.symbol_select(s, True)
        si = mt5.symbol_info(s)
        if si is None:
            print("%-8s unavailable" % s)
            continue
        dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
        cost = SPREAD_PRICE.get(s, 0.0) * dpu + COMMISSION
        bars = closed_bars(s, TF, BARS_REQUEST)
        if len(bars) < 400:
            print("%-8s not enough bars (%d)" % (s, len(bars)))
            continue
        eng = Engines(bars)
        flips = sum(1 for i in range(1, eng.n)
                    if eng.ut_buy[i] or eng.ut_sell[i])
        for mode in ("ut", "confluence"):
            fx, _ = run_backtest(eng, bars, dpu, cost, mode, False, False)
            tx, m = run_backtest(eng, bars, dpu, cost, mode, True, False)
            rf, rt = row(fx), row(tx)
            win = "trail" if rt[1] > rf[1] else "fixed"
            verdicts[(s, mode)] = win
            print("%-8s %-11s %5d %8.2f %-5s %5d %8.2f %-5s %-6s (%d flips/mods)"
                  % (s, mode, rf[0], rf[1], rf[2], rt[0], rt[1], rt[2], win,
                     flips if mode == "ut" else m))
            # EA input InpUseHullFilter=true: block trades against HMA(55) color
            fh, _ = run_backtest(eng, bars, dpu, cost, mode, False, True)
            th, _ = run_backtest(eng, bars, dpu, cost, mode, True, True)
            rh, rth = row(fh), row(th)
            print("%-8s %-11s   hull-filter: fixed %5d %8.2f %-5s | "
                  "trail %5d %8.2f %-5s"
                  % (s, mode, rh[0], rh[1], rh[2], rth[0], rth[1], rth[2]))
    print("\nsummary verdicts:")
    for k in sorted(verdicts):
        print("  %-8s %-11s -> %s" % (k[0], k[1], verdicts[k]))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
