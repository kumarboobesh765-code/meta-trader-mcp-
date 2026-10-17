r"""Backtest the five proposed new strategies side by side on XAUUSD.
Runs ON THE VPS (needs MT5 for bar data).

All five share the rig's conventions so results are comparable with the
existing verdicts (backtest_aetherflow.py / backtest_trail_sweep.py):
  - signals on the last CLOSED bar, market entry at the NEXT bar's open
  - pessimistic same-bar SL check on the entry bar
  - SL 2 x ATR(14, SMA-of-TR on the signal TF) / TP 3 x ATR
  - costs = XAUUSD spread (0.20) + $0.04 per 0.01-lot round trip
  - twins: fixed SL vs trailing SL 0.3/0.7/0.15 ATR (the deployed settings)
  - one position at a time per strategy; signals while busy are skipped
  - 45 days of data fetched, only the LAST 30 days traded (warmup)

Strategies:
  1 TrendPullback   H1 close vs H1 EMA(50) sets trend; M15 pullback touches
                    EMA(21) and closes as a rejection candle in trend direction
  2 NYOpenBreakout  stop-order break of the first 30 min after the NY equity
                    open (16:30-17:00 server), entries within 3 h, 1 trade/day
  3 DonchianH1      close beyond the prior 20-bar H1 channel (H1 ATR for SL/TP)
  4 ATRExpansion    M15 range > 1.8 x ATR closing in the extreme third,
                    only in the H1 EMA(50) trend direction
  5 UTBotH1Filter   M15 UT Bot (2.0/6) flips taken only in the direction of
                    the H1 supertrend (10 / 3.0)

Usage: python C:/FTTest/scripts/backtest_new_candidates.py [--days 30]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_aetherflow import (ut_bot_series, sma_atr_at, tr_series,
                                 walk_exit_fixed, walk_exit_trail)
from forward_test import closed_bars, load_env

BPD = {"M15": 96, "H1": 24}
FETCH_DAYS = 45


# ------------------------------------------------------------------ helpers
def ema_series(vals, period):
    out = [None] * len(vals)
    k = 2.0 / (period + 1)
    prev = None
    for i, v in enumerate(vals):
        prev = v if prev is None else v * k + prev * (1 - k)
        out[i] = prev
    return out


def supertrend_dir(bars, period=10, factor=3.0):
    """+1 = uptrend, -1 = downtrend (Pine-internal dir is -1=up; reversed here
    to keep this module's historical contract -- sig_ut_h1filter buys on +1).

    FIXED 2026-09-30: the first port froze (2759/2760 bars 'up' while gold
    fell 4824->4160). Two bugs vs canonical Pine ta.supertrend:
      1. flips were tested against the FRESH band (up/dn, which sits
         factor*ATR away from price every bar) instead of the RATCHETED band;
      2. the AetherFlow branch-order bug (downtrend state tested the lower
         band and vice versa).
    Correct: downtrend (st=upper band) flips up on close > ratcheted ub;
    uptrend (st=lower band) flips down on close < ratcheted lb.
    ATR = Wilder RMA seeded with the SMA of the first `period` TRs -- exact
    parity with scripts/backtest_supertrend.py and the deployed
    FTTest_supertrend EA (CalcSupertrendFT in FTTestCore.mqh).
    """
    trs = tr_series(bars)
    # Wilder RMA, SMA-seeded (NOT the first-TR seed: it diverged for days)
    p = min(period, len(trs))
    seed = sum(trs[:p]) / p
    atr = [0.0] * len(trs)
    for i, tr in enumerate(trs):
        atr[i] = seed if i < period else (atr[i - 1] * (period - 1) + tr) / period
    n = len(bars)
    pine = [0] * n          # Pine convention: -1 = uptrend, +1 = downtrend
    ub = [0.0] * n
    lb = [0.0] * n
    for i in range(n):
        src = (bars[i]["high"] + bars[i]["low"]) / 2.0
        up = src + factor * atr[i]
        dn = src - factor * atr[i]
        if i == 0:
            ub[i], lb[i], pine[i] = up, dn, 1
            continue
        plb, pub = lb[i - 1], ub[i - 1]
        lb[i] = dn if (dn > plb or bars[i - 1]["close"] < plb) else plb
        ub[i] = up if (up < pub or bars[i - 1]["close"] > pub) else pub
        if pine[i - 1] == 1:      # downtrend: st == upper band
            pine[i] = -1 if bars[i]["close"] > ub[i] else 1
        else:                     # uptrend: st == lower band
            pine[i] = 1 if bars[i]["close"] < lb[i] else -1
    return [-d for d in pine]     # module contract: +1 = uptrend


def h1_index_map(m15, h1):
    """For each M15 bar: index of the last H1 bar fully CLOSED by its open."""
    out = [0] * len(m15)
    j = -1
    for i, b in enumerate(m15):
        t = b["time"]
        while j + 1 < len(h1) and h1[j + 1]["time"] + 3600 <= t:
            j += 1
        out[i] = j
    return out


# ------------------------------------------------------------- event runner
def market_events(sigs, bars):
    """sigs: [(i, side, a)] -> event dicts, entry at next bar open."""
    out = []
    for i, side, a in sigs:
        px = bars[i]["close"]
        sl, tp = (px - 2 * a, px + 3 * a) if side == "buy" else (px + 2 * a, px - 3 * a)
        out.append({"sig_i": i, "side": side, "sl": sl, "tp": tp,
                    "entry_px": None, "entry_i": i + 1, "a": a})
    return out


def run(events, bars, dpu, cost, trailing):
    trades, mods = [], 0
    busy = -1
    for ev in events:
        if ev["sig_i"] <= busy:
            continue
        side, sl, tp, a = ev["side"], ev["sl"], ev["tp"], ev["a"]
        if ev["entry_px"] is None:
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
        else:
            entry = ev["entry_px"]
            start = ev["entry_i"]
        if trailing:
            px, ex_i, m = walk_exit_trail(side, entry, sl, tp, a, bars, start)
            mods += m
        else:
            px, ex_i = walk_exit_fixed(side, sl, tp, bars, start)
        raw = (px - entry) if side == "buy" else (entry - px)
        trades.append(raw * dpu - cost)
        busy = ex_i
    return trades, mods


def row(trades):
    if not trades:
        return (0, 0.0, "n/a", 0.0)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
    return (len(trades), sum(trades), pf, 100.0 * len(wins) / len(trades))


# ----------------------------------------------------------- signal engines
def sig_trendpullback(m15, h1, hmap, trs15, trs1, t0):
    c1 = [b["close"] for b in h1]
    ema50 = ema_series(c1, 50)
    ema21 = ema_series([b["close"] for b in m15], 21)
    sigs = []
    for i in range(2, len(m15) - 1):
        if m15[i]["time"] < t0:
            continue
        j = hmap[i]
        if j < 60:
            continue
        a = sma_atr_at(trs15, i)
        if not a:
            continue
        b = m15[i]
        if c1[j] > ema50[j] and b["low"] <= ema21[i] and b["close"] > b["open"]:
            sigs.append((i, "buy", a))
        elif c1[j] < ema50[j] and b["high"] >= ema21[i] and b["close"] < b["open"]:
            sigs.append((i, "sell", a))
    return sigs


def sig_nybreakout(m15, trs15, t0, range_at=17 * 60, window_min=180):
    """Range = the two M15 bars opening 16:30/16:45 server; break entries
    within `window_min` minutes; fills AT the range price (stop order)."""
    idx = {b["time"]: k for k, b in enumerate(m15)}
    events = []
    n = len(m15)
    for k, b in enumerate(m15):
        t = b["time"]
        if t < t0:
            continue
        tod = datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None)
        if (tod.hour * 60 + tod.minute) != range_at:
            continue
        i1, i2 = idx.get(t - 1800), idx.get(t - 900)
        if i1 is None or i2 is None:
            continue
        hi = max(m15[i1]["high"], m15[i2]["high"])
        lo = min(m15[i1]["low"], m15[i2]["low"])
        a = sma_atr_at(trs15, i2)
        if not a or hi == lo:
            continue
        span = window_min // 15
        for k2 in range(k, min(k + span, n)):
            b2 = m15[k2]
            hb, hs = b2["high"] >= hi, b2["low"] <= lo
            if hb and hs:
                break                      # ambiguous bar -> stand aside
            if hb:
                events.append({"sig_i": k2, "side": "buy", "sl": hi - 2 * a,
                               "tp": hi + 3 * a, "entry_px": hi, "entry_i": k2,
                               "a": a})
                break
            if hs:
                events.append({"sig_i": k2, "side": "sell", "sl": lo + 2 * a,
                               "tp": lo - 3 * a, "entry_px": lo, "entry_i": k2,
                               "a": a})
                break
    return events


def sig_donchian(h1, trs1, t0, length=20):
    sigs = []
    for i in range(length + 1, len(h1) - 1):
        if h1[i]["time"] < t0:
            continue
        a = sma_atr_at(trs1, i)
        if not a:
            continue
        hh = max(h1[k]["high"] for k in range(i - length, i))
        ll = min(h1[k]["low"] for k in range(i - length, i))
        c = h1[i]["close"]
        if c > hh:
            sigs.append((i, "buy", a))
        elif c < ll:
            sigs.append((i, "sell", a))
    return sigs


def sig_atrexpansion(m15, h1, hmap, trs15, trs1, t0, k_atr=1.8):
    c1 = [b["close"] for b in h1]
    ema50 = ema_series(c1, 50)
    sigs = []
    for i in range(15, len(m15) - 1):
        if m15[i]["time"] < t0:
            continue
        a = sma_atr_at(trs15, i)
        if not a:
            continue
        b = m15[i]
        rng = b["high"] - b["low"]
        if rng <= k_atr * a:
            continue
        j = hmap[i]
        if j < 60:
            continue
        third = rng / 3.0
        if c1[j] > ema50[j] and b["close"] >= b["high"] - third:
            sigs.append((i, "buy", a))
        elif c1[j] < ema50[j] and b["close"] <= b["low"] + third:
            sigs.append((i, "sell", a))
    return sigs


def sig_ut_h1filter(m15, h1, hmap, trs15, t0):
    ut_b, ut_s, _ = ut_bot_series(m15)
    sdir = supertrend_dir(h1)
    sigs = []
    for i in range(2, len(m15) - 1):
        if m15[i]["time"] < t0:
            continue
        j = hmap[i]
        if j < 20:
            continue
        a = sma_atr_at(trs15, i)
        if not a:
            continue
        if ut_b[i] and sdir[j] == 1:
            sigs.append((i, "buy", a))
        elif ut_s[i] and sdir[j] == -1:
            sigs.append((i, "sell", a))
    return sigs


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    load_env()
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info(args.symbol)
    mt5.symbol_select(args.symbol, True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = ba.SPREAD_PRICE.get(args.symbol, 0.0) * dpu + ba.COMMISSION

    m15 = closed_bars(args.symbol, "M15", FETCH_DAYS * BPD["M15"] + 300)
    h1 = closed_bars(args.symbol, "H1", FETCH_DAYS * BPD["H1"] + 300)
    mt5.shutdown()
    if len(m15) < 2000 or len(h1) < 500:
        print("not enough bars (m15=%d h1=%d)" % (len(m15), len(h1)))
        return 1

    t0 = m15[-1]["time"] - args.days * 86400
    trs15 = tr_series(m15)
    trs1 = tr_series(h1)
    hmap = h1_index_map(m15, h1)

    # deployed rig trail settings (0.3/0.7/0.15) for the -T twins
    ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = 0.3, 0.7, 0.15

    strategies = [
        ("TrendPullback", market_events(
            sig_trendpullback(m15, h1, hmap, trs15, trs1, t0), m15), m15),
        ("NYOpenBreakout", sig_nybreakout(m15, trs15, t0), m15),
        ("DonchianH1", market_events(
            sig_donchian(h1, trs1, t0), h1), h1),
        ("ATRExpansion", market_events(
            sig_atrexpansion(m15, h1, hmap, trs15, trs1, t0), m15), m15),
        ("UTBotH1Filter", market_events(
            sig_ut_h1filter(m15, h1, hmap, trs15, t0), m15), m15),
    ]

    print("XAUUSD candidate backtest: last %dd traded of %dd data | SL 2 / TP 3 ATR "
          "| cost $%.2f/trade (0.01 lot) | trail twin 0.3/0.7/0.15"
          % (args.days, FETCH_DAYS, cost))
    print("%-16s %22s   %22s   %s"
          % ("STRATEGY", "FIXED n/net/PF/win%", "TRAIL n/net/PF/win%", "RANK"))
    results = []
    for name, events, bars in strategies:
        tf_, tn_, tf_pf, tf_w = row(run(events, bars, dpu, cost, False)[0])
        tt, tmods = run(events, bars, dpu, cost, True)
        tt_n, tt_net, tt_pf, tt_w = row(tt)
        avg = (tt_net / tt_n) if tt_n else 0.0
        results.append((tt_net, name, (tf_, tn_, tf_pf, tf_w),
                        (tt_n, tt_net, tt_pf, tt_w), avg))
    rank = sorted(results, key=lambda r: r[0], reverse=True)
    rank_of = {name: i + 1 for i, (_, name, _, _, _) in enumerate(rank)}
    for tt_net, name, f, t, avg in results:
        print("%-16s %4d %+9.2f %-5s %3.0f%%   %4d %+9.2f %-5s %3.0f%%   #%d"
              % (name, f[0], f[1], f[2], f[3], t[0], t[1], t[2], t[3],
                 rank_of[name]))
    print("\nRANKING by trail-twin net (deployed exit style):")
    for i, (net, name, f, t, avg) in enumerate(rank, 1):
        tag = "STRONG" if t[0] >= 15 and net > 0 else \
              "PROMISING (low sample)" if net > 0 else "REJECT"
        print("  %d. %-16s trail net %+9.2f  (%d trades, avg %+.2f, PF %s)  %s"
              % (i, name, net, t[0], avg, t[2], tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
