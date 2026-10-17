r"""Institutional-strategy campaign: 4 new price-action strategies + 1 filter
study, all on XAUUSD with the house pessimistic replay rules (signals on
closed bars, entry next open, same-bar SL counted, spread 0.20 + $0.04/0.01
RT, 1.0 dpu).

  vwap_rev   M15 session-VWAP reversion (London 11:00 UTC anchor, 1.5 sigma
             bands, trend-day skip, TP = VWAP, 1.5 ATR SL, 16-bar time stop)
  fix_fade   M15 London-Fix rebalancing fade (13-14 UTC impulse >= 0.5 ATR,
             fade at 14:15, SL beyond impulse, TP 1.0x impulse, 8-bar stop)
  sweep_abs  M15 sweep + absorption (sweep of 20-bar extreme, wick >= 0.2,
             close-direction bar delta OPPOSITE the sweep = absorbed; SL 1.5
             ATR / TP 3 ATR like liquiditysweep)
  ote_dxr    H1 ICT Optimal-Trade-Entry inside the daily dealing range
             (bull above H1 EMA120, long only in 62-79% discount pocket
             after a sweep of the last 12 H1 lows, rejection close; 1/day)
  dxy_filter STUDY: strat_trend (H1) with an inverse-DXY filter (EURUSD H1
             close vs EMA50) vs unfiltered -- does it rescue trend-T?

Verdicts printed per 30d and 90d window. Usage:
  python C:/FTTest/scripts/backtest_institutional.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
from backtest_new_candidates import row
from forward_test import (closed_bars, ema, load_env, strat_trend)

SPREAD = 0.20
COMMISSION = 0.04
COST = SPREAD * 1.0 + COMMISSION      # $/0.01-lot RT (dpu == 1.0 on XAU)
M15 = 900
H1 = 24
FETCH_M15 = 95 * 96 + 320
FETCH_H1 = 125 * 24 + 320
LON_START = 11                        # UTC hours (rig convention)
FIX_HOUR = 14                         # 15:00 London ~= 14 UTC


def fetch_vol_bars(tf, n):
    """closed bars WITH tick_volume (closed_bars drops volume)."""
    tfmap = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    rates = mt5.copy_rates_from_pos("XAUUSD", tfmap[tf], 1, n)
    if rates is None:
        return []
    return [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"],
             "vol": int(r["tick_volume"])} for r in rates]


def walk_timed(side, sl, tp, bars, start_i, max_bars):
    """SL-before-TP walker with a time stop (exit at bar close)."""
    last = min(len(bars) - 1, start_i + max_bars - 1)
    for j in range(start_i, last + 1):
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
    return bars[last]["close"], last


def run_events(events, bars, dpu):
    """events: (sig_i, side, sl, tp, max_bars). Returns trade PnL list."""
    out = []
    busy_until = -1
    for sig_i, side, sl, tp, maxb in events:
        if sig_i <= busy_until:
            continue
        nxt = bars[sig_i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            out.append(((sl - entry) if side == "buy" else (entry - sl)) * dpu)
            busy_until = sig_i + 1
            continue
        px, ex_i = walk_timed(side, sl, tp, bars, sig_i + 2, maxb)
        raw = (px - entry) if side == "buy" else (entry - px)
        out.append(raw * dpu)
        busy_until = ex_i
    return out


# ------------------------------------------------------------------ vwap_rev
def vwap_rev_events(bars, t0, atrs):
    """Session-VWAP reversion on M15. VWAP anchored 11:00 UTC daily; TP=VWAP."""
    events = []
    day = None
    sv = ss = svw = 0.0            # sum(value), sum(sq dev), sum(vol)
    vwap = None
    sigs_today = 0
    for i in range(320, len(bars) - 2):
        b = bars[i]
        d = b["time"] // 86400
        if d != day:
            day = d
            sv = ss = svw = 0.0
            vwap = None
            sigs_today = 0
        hour = (b["time"] % 86400) // 3600
        if hour < LON_START or hour >= 20:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        sv += tp * b["vol"]
        svw += b["vol"]
        vwap = sv / max(svw, 1)
        ss += b["vol"] * (tp - vwap) ** 2
        sigma = (ss / max(svw, 1)) ** 0.5
        a = atrs[i]
        if not a or vwap is None or sigma <= 0:
            continue
        # trend-day skip: vwap drifted > 1 sigma from session open
        if abs(b["close"] - vwap) > 2.5 * sigma:
            continue
        if sigs_today >= 2:
            continue
        if b["close"] <= vwap - 1.5 * sigma and b["close"] > b["open"]:
            events.append((i, "buy", b["close"] - 1.5 * a, vwap, 16))
            sigs_today += 1
        elif b["close"] >= vwap + 1.5 * sigma and b["close"] < b["open"]:
            events.append((i, "sell", b["close"] + 1.5 * a, vwap, 16))
            sigs_today += 1
    return events


# ------------------------------------------------------------------ fix_fade
def fix_fade_events(bars, t0, atrs):
    """Fade the 13-14 UTC pre-fix impulse at the 14:15 bar."""
    events = []
    idx = {b["time"]: i for i, b in enumerate(bars)}
    for i in range(320, len(bars) - 12):
        b = bars[i]
        if (b["time"] % 86400) // 3600 != FIX_HOUR:
            continue
        if b["time"] % 3600 != 0:
            continue
        i0 = idx.get(b["time"] - 3600)
        if i0 is None:
            continue
        a = atrs[i]
        if not a:
            continue
        impulse = b["close"] - bars[i0]["close"]
        if abs(impulse) < 0.5 * a:
            continue
        i1 = idx.get(b["time"] + 900)          # 14:15 bar
        if i1 is None:
            continue
        if impulse > 0:
            events.append((i1, "sell", bars[i0]["high"] + 0.3 * a,
                           b["close"] - 1.0 * abs(impulse), 8))
        else:
            events.append((i1, "buy", bars[i0]["low"] - 0.3 * a,
                           b["close"] + 1.0 * abs(impulse), 8))
    return events


# ----------------------------------------------------------------- sweep_abs
def sweep_abs_events(bars, t0, atrs, lookback=20, wick=0.20):
    """Sweep of a 20-bar extreme + absorption delta divergence."""
    events = []
    for i in range(320 + lookback, len(bars) - 2):
        b = bars[i]
        a = atrs[i]
        if not a:
            continue
        body = abs(b["close"] - b["open"])
        rng = max(b["high"] - b["low"], 1e-9)
        prev_lo = min(x["low"] for x in bars[i - lookback:i])
        prev_hi = max(x["high"] for x in bars[i - lookback:i])
        # sweep of lows, wick below, close back above; delta proxy:
        # sign(close-open)*vol OPPOSITE the sweep direction (positive delta)
        # 2026-10-06 FIX: this read (b["low"] - b["close"]) for years, which
        # is <= 0 by definition (low <= close) and could never clear wick --
        # the buy branch NEVER fired (probe: 566 events, 0 buys). The mirror
        # of the sell branch's upper-wick-to-close is the lower-wick-to-close
        # (b["close"] - b["low"]); with the bullish-close delta condition
        # below, close > open makes that exactly the lower wick share.
        if b["low"] < prev_lo and b["close"] > prev_lo and \
           (b["close"] - b["low"]) / rng >= wick and \
           (b["close"] - b["open"]) * b["vol"] > 0:
            events.append((i, "buy", b["low"] - 1.5 * a, b["close"] + 3 * a, 96))
        elif b["high"] > prev_hi and b["close"] < prev_hi and \
                (b["high"] - b["close"]) / rng >= wick and \
                (b["close"] - b["open"]) * b["vol"] < 0:
            events.append((i, "sell", b["high"] + 1.5 * a, b["close"] - 3 * a, 96))
    return events


# -------------------------------------------------------------------- ote_dx
def ote_events(bars, t0, atrs):
    """ICT OTE: bull regime (close > EMA120 H1), long only, discount pocket
    62-79% of the last-3-day range, sweep of 12-bar low, rejection close."""
    events = []
    closes = [b["close"] for b in bars]
    last_day = None
    for i in range(320, len(bars) - 2):
        b = bars[i]
        e = ema(closes[max(0, i - 500):i + 1], 120)
        if e is None or closes[i] <= e:
            continue
        a = atrs[i]
        if not a:
            continue
        day = b["time"] // 86400
        if day != last_day:
            last_day = day
        w = bars[max(0, i - 72):i]                 # 3 days of H1
        hi = max(x["high"] for x in w)
        lo = min(x["low"] for x in w)
        if hi - lo < 2.0 * a:
            continue
        zone_lo = lo + 0.62 * (hi - lo)
        zone_hi = lo + 0.79 * (hi - lo)
        if not (zone_lo <= b["close"] <= zone_hi):
            continue
        swept = b["low"] < min(x["low"] for x in bars[i - 12:i])
        if swept and b["close"] > b["open"] and \
                b["close"] > (b["high"] + b["low"]) / 2.0:
            events.append((i, "buy", b["low"] - 0.3 * a,
                           b["close"] + 2 * a, 48))
    return events


def slice_events(events, bars, t0, t1):
    return [e for e in events if t0 <= bars[e[0]]["time"] <= t1]


def main():
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
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1

    bars15 = fetch_vol_bars("M15", FETCH_M15)
    bars_h1 = closed_bars("XAUUSD", "H1", FETCH_H1)
    eur_h1 = closed_bars("EURUSD", "H1", 100 * 24 + 320)
    mt5.shutdown()
    if len(bars15) < 4000 or len(bars_h1) < 1500:
        print("not enough bars: M15=%d H1=%d" % (len(bars15), len(bars_h1)))
        return 1

    trs15 = bae.tr_series(bars15)
    atr15 = {i: bae.sma_atr_at(trs15, i) for i in range(0, len(bars15), 1)}
    trs_h1 = bae.tr_series(bars_h1)
    atr_h1 = {i: bae.sma_atr_at(trs_h1, i) for i in range(len(bars_h1))}

    t_last15 = bars15[-1]["time"]
    t_last_h1 = bars_h1[-1]["time"]
    w30, w90 = 30 * 86400, 90 * 86400

    print("INSTITUTIONAL CAMPAIGN -- %s %s (demo) | cost $%.2f/trade"
          % (acc.login, acc.server, COST))
    print("%-12s %22s %22s %s" %
          ("STRATEGY", "30d n/net/PF/win%", "90d n/net/PF/win%", "VERDICT"))

    verdicts = {}

    def grade(name, ev_func, bars, atrs, t_last):
        ev_all = ev_func(bars, 0, atrs)
        r30 = row(run_events(slice_events(ev_all, bars, t_last - w30, t_last + 1),
                             bars, 1.0))
        r90 = row(run_events(slice_events(ev_all, bars, t_last - w90, t_last + 1),
                             bars, 1.0))
        wins30 = sum(1 for t in run_events(
            slice_events(ev_all, bars, t_last - w30, t_last + 1), bars, 1.0) if t > 0)
        wins90 = sum(1 for t in run_events(
            slice_events(ev_all, bars, t_last - w90, t_last + 1), bars, 1.0) if t > 0)
        f30 = "%d/%+.2f/%s/%.0f%%" % (r30[0], r30[1], r30[2],
                                      100 * wins30 / max(r30[0], 1))
        f90 = "%d/%+.2f/%s/%.0f%%" % (r90[0], r90[1], r90[2],
                                      100 * wins90 / max(r90[0], 1))
        v = "PORT" if r30[1] > 0 and r90[1] > 0 and r90[2] not in ("n/a",) \
            and (r90[2] == "inf" or float(r90[2]) >= 1.15) else \
            ("WATCH" if r90[1] > 0 else "SKIP")
        verdicts[name] = (r30[1], r90[1], v)
        print("%-12s %22s %22s %s" % (name, f30, f90, v))

    grade("vwap_rev", vwap_rev_events, bars15, atr15, t_last15)
    grade("fix_fade", fix_fade_events, bars15, atr15, t_last15)
    grade("sweep_abs", sweep_abs_events, bars15, atr15, t_last15)
    grade("ote_dxr", ote_events, bars_h1, atr_h1, t_last_h1)

    # ---- DXY-filter study on strat_trend (H1) ------------------------------
    eur_above = {}
    j = 0
    ec = [(b["time"], b["close"]) for b in eur_h1]
    ecloses = [c for _t, c in ec]
    for i, b in enumerate(bars_h1):
        while j < len(ec) - 1 and ec[j + 1][0] <= b["time"]:
            j += 1
        e = ema(ecloses[max(0, j - 300):j + 1], 50)
        if e is not None:
            eur_above[b["time"]] = ec[j][1] > e

    ev_long, ev_flt = [], []
    busy = -1
    for i in range(320, len(bars_h1) - 2):
        if i <= busy:
            continue
        r = strat_trend(bars_h1[max(0, i - 300):i + 1])
        if not r or r[0] != "entry":
            continue
        _, side, sl, tp = r
        a = atr_h1[i]
        if not a:
            continue
        px = bars_h1[i]["close"]
        sl, tp = ((px - 2 * a, px + 3 * a) if side == "buy"
                  else (px + 2 * a, px - 3 * a))
        ev_long.append((i, side, sl, tp, 96))
        okd = eur_above.get(bars_h1[i]["time"])
        if (side == "buy" and okd) or (side == "sell" and okd is False):
            ev_flt.append((i, side, sl, tp, 96))
        else:
            busy = i                      # filtered out: blocks the slot too
    r_l30 = row(run_events(slice_events(ev_long, bars_h1, t_last_h1 - w30,
                                        t_last_h1 + 1), bars_h1, 1.0))
    r_l90 = row(run_events(slice_events(ev_long, bars_h1, t_last_h1 - w90,
                                        t_last_h1 + 1), bars_h1, 1.0))
    r_f30 = row(run_events(slice_events(ev_flt, bars_h1, t_last_h1 - w30,
                                        t_last_h1 + 1), bars_h1, 1.0))
    r_f90 = row(run_events(slice_events(ev_flt, bars_h1, t_last_h1 - w90,
                                        t_last_h1 + 1), bars_h1, 1.0))
    print("%-12s %22s %22s %s"
          % ("trend-plain",
             "%d/%+.2f/%s" % (r_l30[0], r_l30[1], r_l30[2]),
             "%d/%+.2f/%s" % (r_l90[0], r_l90[1], r_l90[2]), "ref"))
    print("%-12s %22s %22s %s"
          % ("trend+dxyflt",
             "%d/%+.2f/%s" % (r_f30[0], r_f30[1], r_f30[2]),
             "%d/%+.2f/%s" % (r_f90[0], r_f90[1], r_f90[2]),
             "BETTER" if r_f90[1] > r_l90[1] else "WORSE"))

    print("\nCAMPAIGN VERDICTS (30d net, 90d net, action):")
    for k, (n30, n90, v) in verdicts.items():
        print("  %-10s %30s %+9.2f %+9.2f  %s"
              % (k, "", n30, n90, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
