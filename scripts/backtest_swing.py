"""Backtest a swing strategy on XAUUSD: fixed SL vs trailing-SL twin.

DESIGN INTENT -- why this is not another trend EA:
The rig already retired `trend` (-$383 both arms) and `supertrend` (-$103 both
arms), which were both "follow the flip" systems that give back open profit on
XAUUSD's violent 1-2 ATR M15 noise. This swing design targets the opposite
failure mode: a wide stop that is RARELY hit, with a target far enough away to
actually be reached, and an optional trail that only ratchets in favour.

  * Bias leg   : last CLOSED H1 close vs EMA50 of H1 closes (structure).
  * Pullback   : the M15 signal bar must touch EMA21 and close as a rejection
                 candle in the bias direction.
  * Confirm    : RSI(14) of the signal bar must agree with the direction
                 (>= 50 long, <= 50 short) -- filters dead-cat bounces.
  * SL/TP      : wide 2.5 ATR stop, 4 ATR target, so the swing leg can breathe.
                 Fixed arm holds it; trail arm ratchets via the shared engine.

Entries are next-bar open with pessimistic same-bar SL, and every function is
causal: the signal function sees only bars up to and including the signal bar.

Usage:
  python backtest_swing.py                 # fixed vs trail, both timeframes
  python backtest_swing.py --days 400      # longer history
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from backtest_new_candidates import run, row  # shared trade engine + costs
import backtest_aetherflow as ba

# walk_exit_trail() -- which run() calls for the trailing arm -- reads the
# MODULE globals TRAIL_ACTIVATE / TRAIL_DIST / TRAIL_STEP from
# backtest_aetherflow, NOT the `trailing` tuple that run() forwards. The tuple
# only decides fixed-vs-trail. So to sweep trail settings you must set these,
# exactly as backtest_trail_full_sweep.py does. Passing different tuples alone
# silently ran the same trail three times and produced identical rows.
def set_trail(act, dist, step):
    ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step

# ----------------------------------------------------------------- constants
SL_ATR = 2.5     # wide stop: this is a swing system, not a scalper
TP_ATR = 4.0     # let the leg actually run
EMA_BIAS = 50    # H1 structure
EMA_PULL = 21    # M15 pullback
RSI_LEN = 14
RSI_MIN = 50.0

# deployed-style trails to compare (act / dist / step), all in ATR units
TRAILS = {
    "legacy 0.10/0.30/0.05": (0.10, 0.30, 0.05),
    "tight  0.05/0.15/0.02": (0.05, 0.15, 0.02),
    "wide   0.50/0.80/0.20": (0.50, 0.80, 0.20),
}

DPU = 1.0     # XAUUSD 0.01 lot = 1 oz = $1.00 per $1 move
COST = 0.20 + 0.04   # spread + commission round trip, matches other harnesses

FETCH_DAYS = 200
BARS_PER_DAY = {"M15": 96, "M30": 48, "H1": 24}


# ------------------------------------------------------------------- helpers
def ema(closes, period):
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(closes[:period]) / period
    for c in closes[period:]:
        e = c * k + e * (1 - k)
    return e


def rsi(closes, period=RSI_LEN):
    if len(closes) < period + 1:
        return None
    g, l = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        h, l_, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l_, abs(h - pc), abs(l_ - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def load(symbol, tf, days):
    n = days * BARS_PER_DAY[tf]
    rates = mt5.copy_rates_from_pos(symbol, {"M15": mt5.TIMEFRAME_M15,
                                             "M30": mt5.TIMEFRAME_M30,
                                             "H1": mt5.TIMEFRAME_H1}[tf],
                                    1, n)
    if rates is None or len(rates) == 0:
        return []
    return [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"]} for r in rates]


# ---------------------------------------------------------------- the signal
def _atr_series(bars, period=14):
    """ATR at each bar index, computed causally in one O(n) pass.

    Calling atr(bars[:i+1]) inside the signal loop rebuilt a full slice per
    bar -- O(n^2) with a list copy per iteration. That made a 400-day walk
    forward unbearably slow (30+ min CPU, no output). Precomputing once is
    numerically identical because ATR here is a plain trailing mean of TR.
    """
    n = len(bars)
    trs = [0.0] * n
    for i in range(1, n):
        h, l_, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs[i] = max(h - l_, abs(h - pc), abs(l_ - pc))
    out = [None] * n
    run = 0.0
    for i in range(1, n):
        run += trs[i]
        if i > period:
            run -= trs[i - period]
        if i >= period:
            out[i] = run / period
    return out


def _rsi_series(closes, period=RSI_LEN):
    """Wilder RSI at each index, one causal pass (same rationale as above)."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    g = [0.0] * n
    l = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        g[i] = max(d, 0.0)
        l[i] = max(-d, 0.0)
    ag = sum(g[1:period + 1]) / period
    al = sum(l[1:period + 1]) / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def _ema_series(vals, period):
    """EMA at each index, causal, one pass."""
    n = len(vals)
    out = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    acc = sum(vals[:period]) / period
    out[period - 1] = acc
    for i in range(period, n):
        acc = vals[i] * k + acc * (1 - k)
        out[i] = acc
    return out


def swing_events(bars, bpd):
    """Emit (sig_i, side, sl, tp, a) for every qualifying closed bar.

    The higher-timeframe bias is approximated by aggregating the HOST series
    into floor(n/bpd) buckets, which is what strat_trendpullback does; the EA
    reads the real H1 feed. Equivalent modulo warmup depth.

    Every indicator is precomputed as a CAUSAL series (each element derived
    only from earlier bars), then indexed at the signal bar -- so this stays
    lookahead-free while running O(n) instead of O(n^2).
    """
    n = len(bars)
    out = []
    nh = n // bpd
    if nh < EMA_BIAS + 5:
        return out
    # precompute H1 bucket closes once
    hc = [bars[n - (nh - h) * bpd + (bpd - 1)]["close"] for h in range(nh)]
    closes = [b["close"] for b in bars]

    e21_series = _ema_series(closes, EMA_PULL)
    atr_series = _atr_series(bars, 14)
    rsi_series = _rsi_series(closes, RSI_LEN)
    h_ema = _ema_series(hc, EMA_BIAS)   # EMA50 of H1 bucket closes

    for i in range(max(EMA_BIAS + EMA_PULL + 2, 60), n):
        # H1 bias from data available at bar i only
        bi = (i + 1) // bpd
        if bi < EMA_BIAS + 2 or bi > nh:
            continue
        # bias uses the EMA of buckets strictly BEFORE the judged bucket
        e50_prev = h_ema[bi - 2] if bi - 2 >= 0 else None
        if e50_prev is None:
            continue
        # Bias is decided by the last CLOSED H1 bucket close vs the EMA50 of
        # the closes BEFORE it (so the comparison never includes the bar being
        # judged). Strict inequality both ways: a close exactly on the EMA is
        # no structure, so it is not a signal.
        if hc[bi - 1] > e50_prev:
            up = True
        elif hc[bi - 1] < e50_prev:
            up = False
        else:
            continue

        a = atr_series[i]
        if not a:
            continue
        r = rsi_series[i]
        if r is None:
            continue
        e21 = e21_series[i]
        if e21 is None:
            continue
        b = bars[i]
        px = b["close"]
        if up and b["low"] <= e21 and b["close"] > b["open"] and r >= RSI_MIN:
            out.append({"sig_i": i, "side": "buy", "sl": px - SL_ATR * a,
                        "tp": px + TP_ATR * a, "a": a, "entry_px": None,
                        "entry_i": None})
        elif (not up) and b["high"] >= e21 and b["close"] < b["open"] and r <= 100 - RSI_MIN:
            out.append({"sig_i": i, "side": "sell", "sl": px + SL_ATR * a,
                        "tp": px - TP_ATR * a, "a": a, "entry_px": None,
                        "entry_i": None})
    return out


# ------------------------------------------------------------------- scoring
def score(trades):
    """run() returns (trades, mods) where trades is a list of FLOATS (net P&L
    per trip), not dicts. row() is the project's own scorer -- use it so the
    numbers stay comparable with the other backtest harnesses."""
    n, net, pf, win = row(trades)
    return {"n": n, "net": net, "win": win, "pf": pf,
            "per": (net / n) if n else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=FETCH_DAYS)
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit("initialize failed: %r" % mt5.last_error())

    for tf in ("M15", "M30", "H1"):
        bars = load(args.symbol, tf, args.days)
        if not bars:
            print("%s: no data" % tf)
            continue
        ev = swing_events(bars, BARS_PER_DAY[tf])
        if not ev:
            print("\n%s (%d bars): no signals" % (tf, len(bars)))
            continue
        print("\n" + "=" * 74)
        print("SWING  %s  bars=%d  signals=%d  window=%dd"
              % (tf, len(bars), len(ev), args.days))
        print("=" * 74)
        print("%-26s %5s %10s %7s %8s %9s"
              % ("arm", "n", "net", "win%", "PF", "per-trip"))
        base, _mods = run(list(ev), bars, DPU, COST, None)
        s = score(base)
        print("%-26s %5d %+10.2f %6.1f%% %8s %+9.2f"
              % ("fixed %.1f/%.1f ATR" % (SL_ATR, TP_ATR), s["n"], s["net"],
                 s["win"], s["pf"], s["per"]))
        for label, trail in TRAILS.items():
            set_trail(*trail)
            tr, _m = run(list(ev), bars, DPU, COST, trail)
            s = score(tr)
            print("%-26s %5d %+10.2f %6.1f%% %8s %+9.2f"
                  % ("trail " + label, s["n"], s["net"], s["win"],
                     s["pf"], s["per"]))
    mt5.shutdown()


if __name__ == "__main__":
    main()