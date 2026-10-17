"""Swing v2: H1 structure + pullback rejection WITH session, volatility and time stops.

v1 (backtest_swing.py) proved the core: wide 2.5 ATR stop, 4 ATR cap, tight
trail -- 52/52 walk-forward windows on M15/M30. v2 layers the three filters
from the strategy spec WITHOUT changing the core signal:

  * SESSION  : London+New York only, 07:00-21:00 broker (UTC+3) on the signal bar.
  * VOL GATE : H1 ATR(14) in the top 60% of its trailing 50-day range, and not
               more than 2x the trailing median (skips dead chop AND news spikes).
  * HH/HL    : bias needs close-vs-EMA50 PLUS rising/falling closes two H1
               buckets apart (a light higher-high / lower-low proxy).
  * BODY     : rejection candle body >= 40% of its range.
  * TIME STOP: flat after 24h if SL/TP/trail hasn't resolved (implemented by
               handing the shared walkers a truncated bar view -- the shared
               run() in backtest_new_candidates has no time-stop concept, and
               touching it would change every other harness).

Every series is causal (indexed strictly before/at the signal bar). Compares
v1 vs v2 events through the SAME exit engine, fixed + tight trail, so the
delta is the filters, not the exits.

Usage (ON THE VPS -- needs MetaTrader5 + terminal data):
  python C:\\FTTest\\scripts\\backtest_swing_v2.py
  python C:\\FTTest\\scripts\\backtest_swing_v2.py --days 400
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from backtest_new_candidates import row
from backtest_aetherflow import walk_exit_fixed, walk_exit_trail
import backtest_swing as v1

# ---------------------------------------------------------------- constants
SL_ATR = v1.SL_ATR          # 2.5 -- untouched core
TP_ATR = v1.TP_ATR          # 4.0 -- untouched core
EMA_BIAS = v1.EMA_BIAS      # 50
EMA_PULL = v1.EMA_PULL      # 21
RSI_LEN = v1.RSI_LEN
RSI_MIN = v1.RSI_MIN        # 50
DPU = v1.DPU
COST = v1.COST
BARS_PER_DAY = v1.BARS_PER_DAY

TIGHT = (0.05, 0.15, 0.02)  # the deployed triple under test

SESS_LO, SESS_HI = 7, 21    # broker (UTC+3) hours, [lo, hi)
VOL_LOOKBACK = 1200         # ~50 days of H1 buckets
VOL_PCTL = 0.40             # keep top 60%
VOL_SPIKE = 2.0             # skip if ATR > 2x trailing median
BODY_MIN = 0.40             # rejection body share of range
HOLD_BARS_24H = None        # resolved per timeframe from BARS_PER_DAY (= bpd)


# ------------------------------------------------------------------ helpers
def _h1_buckets(bars, bpd):
    """Full OHLC buckets (causal grouping, no peeking across bucket edge)."""
    n = len(bars)
    nh = n // bpd
    out = []
    for h in range(nh):
        grp = bars[h * bpd:(h + 1) * bpd]
        out.append({"open": grp[0]["open"], "high": max(g["high"] for g in grp),
                    "low": min(g["low"] for g in grp),
                    "close": grp[-1]["close"]})
    return out


def _bucket_atr(hb, period=14):
    n = len(hb)
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(hb[i]["high"] - hb[i]["low"],
                     abs(hb[i]["high"] - hb[i - 1]["close"]),
                     abs(hb[i]["low"] - hb[i - 1]["close"]))
    out = [None] * n
    run = 0.0
    for i in range(1, n):
        run += trs[i]
        if i > period:
            run -= trs[i - period]
        if i >= period:
            out[i] = run / period
    return out


def _pct_rank(vals):
    """Percentile rank of the last element within vals (all causal)."""
    last = vals[-1]
    return sum(1 for x in vals if x <= last) / len(vals)


def _median(xs):
    s = sorted(xs)
    m = len(s) // 2
    return (s[m - 1] + s[m]) / 2.0 if len(s) % 2 == 0 else s[m]


def swing_events_v2(bars, bpd):
    """v1 signal + session + vol-gate + HH/HL + body filters. Causal."""
    n = len(bars)
    nh = n // bpd
    if nh < EMA_BIAS + 5:
        return [], {"sess": 0, "vol": 0, "hhhl": 0, "body": 0}
    hb = _h1_buckets(bars, bpd)
    hc = [h["close"] for h in hb]
    closes = [b["close"] for b in bars]

    e21_series = v1._ema_series(closes, EMA_PULL)
    atr_series = v1._atr_series(bars, 14)
    rsi_series = v1._rsi_series(closes, RSI_LEN)
    h_ema = v1._ema_series(hc, EMA_BIAS)
    h_atr = _bucket_atr(hb, 14)

    out = []
    veto = {"sess": 0, "vol": 0, "hhhl": 0, "body": 0}
    for i in range(max(EMA_BIAS + EMA_PULL + 2, 60), n):
        bi = (i + 1) // bpd
        if bi < EMA_BIAS + 2 or bi > nh:
            continue
        e50_prev = h_ema[bi - 2] if bi - 2 >= 0 else None
        if e50_prev is None:
            continue
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

        # --- core v1 trigger (unchanged) ---
        if up:
            if not (b["low"] <= e21 and b["close"] > b["open"] and r >= RSI_MIN):
                continue
            side = "buy"
        else:
            if not (b["high"] >= e21 and b["close"] < b["open"] and r <= 100 - RSI_MIN):
                continue
            side = "sell"

        # --- v2 filters, cheapest first ---
        hr = ((b["time"] + 3 * 3600) % 86400) // 3600
        if not (SESS_LO <= hr < SESS_HI):
            veto["sess"] += 1
            continue
        # HH/HL proxy: closes rising/falling two buckets apart
        if bi - 3 < 0:
            continue
        if up and not (hc[bi - 1] > hc[bi - 3]):
            veto["hhhl"] += 1
            continue
        if not up and not (hc[bi - 1] < hc[bi - 3]):
            veto["hhhl"] += 1
            continue
        # body share
        rng = b["high"] - b["low"]
        if rng <= 0 or abs(b["close"] - b["open"]) / rng < BODY_MIN:
            veto["body"] += 1
            continue
        # vol gate on H1 ATR, trailing window strictly before current bucket
        ha = h_atr[bi - 1]
        win = [x for x in h_atr[max(0, bi - 1 - VOL_LOOKBACK):bi - 1] if x]
        if not ha or len(win) < 100:
            continue
        if _pct_rank(win + [ha]) < VOL_PCTL or ha > VOL_SPIKE * _median(win):
            veto["vol"] += 1
            continue

        sl, tp = (px - SL_ATR * a, px + TP_ATR * a) if side == "buy" \
            else (px + SL_ATR * a, px - TP_ATR * a)
        out.append({"sig_i": i, "side": side, "sl": sl, "tp": tp,
                    "a": a, "entry_px": None, "entry_i": None})
    return out, veto


def run_capped(events, bars, dpu, cost, trailing, cap_bars):
    """Shared walkers, but each trade sees bars only up to entry+cap.

    The walkers' fallthrough returns the last visible close, so a trade that
    never hits SL/TP/trail inside the window exits flat-ish at the 24h mark.
    Same busy-slot semantics as the shared run().
    """
    trades, mods = [], 0
    busy = -1
    for ev in events:
        if ev["sig_i"] <= busy:
            continue
        side, sl, tp, a = ev["side"], ev["sl"], ev["tp"], ev["a"]
        i = ev["sig_i"]
        if i + 1 >= len(bars):
            break
        entry = bars[i + 1]["open"]
        if (side == "buy" and bars[i + 1]["low"] <= sl) or \
           (side == "sell" and bars[i + 1]["high"] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            trades.append(raw * dpu - cost)
            busy = i + 1
            continue
        start = i + 2
        view = bars[:start + cap_bars]
        if trailing:
            px, ex_i, m = walk_exit_trail(side, entry, sl, tp, a, view, start)
            mods += m
        else:
            px, ex_i = walk_exit_fixed(side, sl, tp, view, start)
        raw = (px - entry) if side == "buy" else (entry - px)
        trades.append(raw * dpu - cost)
        busy = ex_i
    return trades, mods


def score(trades):
    n, net, pf, win = row(trades)
    return {"n": n, "net": net, "win": win, "pf": pf,
            "per": (net / n) if n else 0.0}


def fmt(s):
    return "%5d %+10.2f %6.1f%% %8s %+9.2f" % (s["n"], s["net"], s["win"],
                                              s["pf"], s["per"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=v1.FETCH_DAYS)
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit("initialize failed: %r" % mt5.last_error())

    for tf in ("M15", "M30"):
        bpd = BARS_PER_DAY[tf]
        bars = v1.load(args.symbol, tf, args.days)
        if not bars:
            print("%s: no data" % tf)
            continue
        ev1 = v1.swing_events(bars, bpd)
        ev2, veto = swing_events_v2(bars, bpd)
        print("\n" + "=" * 78)
        print("SWING v1-vs-v2  %s  bars=%d  v1 signals=%d  v2 signals=%d  window=%dd"
              % (tf, len(bars), len(ev1), len(ev2), args.days))
        print("v2 vetoes (of v1 triggers): %s" % veto)
        print("=" * 78)
        print("%-30s %5s %10s %7s %8s %9s"
              % ("arm", "n", "net", "win%", "PF", "per-trip"))
        for label, ev, trail, capped in (
                ("v1 fixed 2.5/4.0 (no tstop)", ev1, None, False),
                ("v1 trail tight (no tstop)", ev1, TIGHT, False),
                ("v1 fixed + 24h tstop", ev1, None, True),
                ("v1 trail + 24h tstop", ev1, TIGHT, True),
                ("v2 fixed + filters + tstop", ev2, None, True),
                ("v2 trail + filters + tstop", ev2, TIGHT, True)):
            if trail:
                v1.set_trail(*trail)
            if capped:
                tr, _m = run_capped(list(ev), bars, DPU, COST, trail, bpd)
            else:
                from backtest_new_candidates import run as shared_run
                tr, _m = shared_run(list(ev), bars, DPU, COST, trail)
            print("%-30s %s" % (label, fmt(score(tr))))
    mt5.shutdown()


if __name__ == "__main__":
    main()
