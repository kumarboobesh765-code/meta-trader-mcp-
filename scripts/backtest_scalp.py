r"""Session-break micro-scalp (M5) -- fixed vs trail, cost-aware, 200 days.

Strategy (user-approved spec):
  * Sessions: London 07:00-10:00, NY 13:30-16:30; flat elsewhere.
  * Level: London = prior 15-min (last 3 M5 bars) high/low;
    NY = same-day Asian (00:00-07:00) range high/low.
  * Trigger: M5 CLOSE beyond the level AND tick volume >= 1.5x its
    own 20-bar median.  Entry: next bar open.
  * SL 0.4x H1 ATR(14) / TP 1.0x H1 ATR(14); ATR is causal -- the
    last H1 bar CLOSED at signal time (H1 bar h is closed once
    h+3600 <= signal_bar_time+300).
  * Trail arm: 0.05 / 0.15 / 0.02 (activate / dist / step), ATR
    units of the SAME signal-time H1 ATR (NOT run_cost()'s
    abs(entry-sl)/1.5 normalisation -- that assumes 1.5-ATR stops).
  * Hard time stop 45 min = 9 M5 bars: exit at the close of the 9th
    bar after the entry bar (both arms, so they stay comparable).
  * Risk manager: max 2 concurrent trades, one per direction; 3 flat
    bars (15 min) cooldown after a LOSS; max 3 trades/day.
  * Cost $0.24/round-trip deducted (house: 0.20 spread + 0.04 comm);
    sensitivity row at $0.35 (IOC slippage).

SESSION-WINDOW INTERPRETATION (verified on the VPS 2026-10-05):
bar epochs are broker-server wall (measured tick offset = UTC+3).  The
spec's windows are labelled London/NY.  Read as UTC they land exactly
on the London open (07:00 UTC BST / 08:00 UTC GMT) and the NY open
(13:30 UTC EDT / 14:30 UTC EST) -- interpretation A, primary.
Read as literal broker-wall hours they sit at 04:00-07:00 and
10:30-13:30 UTC, i.e. BEFORE the sessions they name --
interpretation B, reported for completeness.  Both are backtested.

Runs ON THE VPS (needs MetaTrader5 + terminal data).
Usage: python C:\FTTest\scripts\backtest_scalp.py
"""
import os
import statistics
import sys
from bisect import bisect_right
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
from backtest_institutional import walk_timed
from backtest_new_candidates import row

SYMBOL = "XAUUSD"
M5_TRADE_BARS = 200 * 280        # ~200 trading days (~280 M5 bars/day
                                 # once the ~40-min daily break is counted)
M5_WARMUP = 2000                 # >> 20-bar median + 3-bar level needs
M5_FETCH = M5_TRADE_BARS + M5_WARMUP
H1_FETCH = 6000                  # ~365 calendar days of H1, covers the window
SL_ATR, TP_ATR = 0.4, 1.0
TRAIL_ACT, TRAIL_DIST, TRAIL_STEP = 0.05, 0.15, 0.02
COST_BASE = 0.24
COST_SENS = (0.24, 0.35)
TIME_STOP_BARS = 9               # 45 min: entry bar + 8 more
COOLDOWN_BARS = 3                # 3 flat bars after a loss
MAX_DAY = 3
MAX_CONC = 2
VOL_LEN = 20
VOL_MULT = 1.5
LON_WIN = (7 * 3600, 10 * 3600)               # UTC seconds
NY_WIN = (13 * 3600 + 1800, 16 * 3600 + 1800) # UTC seconds
ASIAN_END = 7 * 3600


# ------------------------------------------------------------------ data
def fetch_vol_bars(tf, n):
    """closed bars WITH tick_volume (closed_bars drops volume)."""
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 1, n)
    if rates is None:
        return []
    return [{"time": int(r["time"]), "open": float(r["open"]),
             "high": float(r["high"]), "low": float(r["low"]),
             "close": float(r["close"]),
             "vol": int(r["tick_volume"])} for r in rates]


def measure_offset_hours():
    """Server-epoch offset from true UTC, whole hours, from a LIVE tick."""
    t = mt5.symbol_info_tick(SYMBOL)
    now = datetime.now().timestamp()
    if t is None or not t.time:
        return None
    return int(round((t.time - now) / 3600.0))


def activity_profile(bars):
    """Top server-wall hours by tick volume (epoch-frame cross-check)."""
    hrs = {}
    for b in bars:
        h = (b["time"] % 86400) // 3600
        hrs[h] = hrs.get(h, 0) + b["vol"]
    return sorted(hrs.items(), key=lambda kv: -kv[1])[:6]


# ---------------------------------------------------------------- signals
def gen_events(bars, h1_times, h1_trs, mode):
    """mode 'utc': session labels are UTC (bar.time - offset).
       mode 'server': session labels are literal broker-wall hours."""
    off = SERVER_OFFSET * 3600
    evs = []
    asian = {}                       # day -> [hi, lo]
    for i in range(320, len(bars) - 1):
        b = bars[i]
        t = b["time"] - (off if mode == "utc" else 0)
        tod = t % 86400
        day = t // 86400
        if tod < ASIAN_END:          # accumulate the Asian range
            ah, al = asian.get(day, (-1e30, 1e30))
            asian[day] = (max(ah, b["high"]), min(al, b["low"]))
        if i < M5_WARMUP:
            continue
        ldn = LON_WIN[0] <= tod < LON_WIN[1]
        ny = NY_WIN[0] <= tod < NY_WIN[1]
        if not (ldn or ny):
            continue
        if ldn:
            lhi = max(bars[i - 3]["high"], bars[i - 2]["high"],
                      bars[i - 1]["high"])
            llo = min(bars[i - 3]["low"], bars[i - 2]["low"],
                      bars[i - 1]["low"])
            sess = "LDN"
        else:
            if day not in asian:
                continue
            lhi, llo = asian[day]
            sess = "NY"
        side = None
        if b["close"] > lhi:
            side = "buy"
        elif b["close"] < llo:
            side = "sell"
        if side is None:
            continue
        med = statistics.median([bars[k]["vol"] for k in range(i - VOL_LEN, i)])
        if med <= 0 or b["vol"] < VOL_MULT * med:
            continue
        # causal H1 ATR: last H1 bar closed at signal time
        idx = bisect_right(h1_times, b["time"] - 3300) - 1
        if idx < 14:
            continue
        a = bae.sma_atr_at(h1_trs, idx, 14)
        if a is None or a <= 0:
            continue
        px = b["close"]
        if side == "buy":
            sl, tp = px - SL_ATR * a, px + TP_ATR * a
        else:
            sl, tp = px + SL_ATR * a, px - TP_ATR * a
        evs.append({"i": i, "side": side, "sl": sl, "tp": tp,
                    "a": a, "sess": sess, "day": day})
    return evs


# ---------------------------------------------------------------- runner
def run_events(events, bars, trailing, cost):
    """Shared risk manager: max 2 concurrent (1/direction), 3-bar
    loss cooldown, 3 trades/day.  Returns (trades, stats)."""
    trades = []                      # (raw_pnl, sess, day, hold_bars)
    open_t = []                      # (side, exit_i)
    day_n = {}
    cool = -1
    rej = {"cool": 0, "day": 0, "conc": 0}
    for ev in events:
        i = ev["i"]
        if i + 1 >= len(bars):
            break
        if i < cool:
            rej["cool"] += 1
            continue
        if day_n.get(ev["day"], 0) >= MAX_DAY:
            rej["day"] += 1
            continue
        live = [t for t in open_t if t[1] >= i + 1]
        if len(live) >= MAX_CONC or \
           any(t[0] == ev["side"] for t in live):
            rej["conc"] += 1
            continue
        entry = bars[i + 1]["open"]
        sl, tp, a = ev["sl"], ev["tp"], ev["a"]
        b1 = bars[i + 1]
        if (ev["side"] == "buy" and b1["low"] <= sl) or \
           (ev["side"] == "sell" and b1["high"] >= sl):
            # pessimistic same-bar SL on the entry bar
            raw = (sl - entry) if ev["side"] == "buy" else (entry - sl)
            ex_i = i + 1
        else:
            start = i + 2
            view = bars[:start + TIME_STOP_BARS - 1]   # last visible = 9th bar
            if trailing:
                px, ex_i, _ = bae.walk_exit_trail(
                    ev["side"], entry, sl, tp, a, view, start)
            else:
                px, ex_i = walk_timed(ev["side"], sl, tp, view, start,
                                      TIME_STOP_BARS - 1)
            raw = (px - entry) if ev["side"] == "buy" else (entry - px)
        trades.append((raw, ev["sess"], ev["day"], ex_i - i, a))
        day_n[ev["day"]] = day_n.get(ev["day"], 0) + 1
        # still open during the new trade's entry bar (i+1)?
        open_t = [t for t in open_t if t[1] >= i + 1]
        open_t.append((ev["side"], ex_i))
        if raw <= 0:
            cool = ex_i + COOLDOWN_BARS
    return trades, rej


# ---------------------------------------------------------------- report
def fmt_row(n, net, pf, win):
    return "%5d %+10.2f %8s %6.1f%% %+8.2f" % (n, net, pf, win,
                                                 (net / n) if n else 0.0)


def stats(trades, cost):
    nets = [t[0] - cost for t in trades]
    n, net, pf, win = row(nets)
    return {"n": n, "net": net, "pf": pf, "win": win,
            "raw_sum": sum(t[0] for t in trades)}


def report(name, events, trades, rej):
    print("--- %s ---" % name)
    print("signals: %d generated | %d accepted | rejects: cooldown %d, "
          "day-cap %d, concurrency %d"
          % (len(events), len(trades), rej["cool"], rej["day"], rej["conc"]))
    if not trades:
        print("NO TRADES")
        return
    atrs = [t[4] for t in trades]
    print("avg signal-time H1 ATR(14): $%.2f (SL ~$%.2f, TP ~$%.2f)"
          % (sum(atrs) / len(atrs), SL_ATR * sum(atrs) / len(atrs),
             TP_ATR * sum(atrs) / len(atrs)))
    for cost in COST_SENS:
        s = stats(trades, cost)
        print("cost $%.2f: %s   (n net PF win%%/per-trip)"
              % (cost, fmt_row(s["n"], s["net"], s["pf"], s["win"])))
    s = stats(trades, COST_BASE)
    for sess in ("LDN", "NY"):
        st = [t for t in trades if t[1] == sess]
        ss = stats(st, COST_BASE)
        print("  %-3s %s" % (sess, fmt_row(ss["n"], ss["net"], ss["pf"],
                                             ss["win"])))
    # per-30d net (base cost), fixed reference for decay check
    days = sorted({t[2] for t in trades})
    if days:
        d0 = days[0]
        buckets = {}
        for t in trades:
            buckets.setdefault((t[2] - d0) // 30, []).append(t[0])
        line = []
        for k in sorted(buckets):
            nets = [v - COST_BASE for v in buckets[k]]
            line.append("%d:%+0.0f" % (k, sum(nets)))
        print("  per-30d net: %s" % "  ".join(line))
    worst = min(t[0] - COST_BASE for t in trades)
    avg_hold = sum(t[3] for t in trades) / len(trades)
    print("  worst trade $%.2f | avg hold %.1f bars (%.0f min)"
          % (worst, avg_hold, avg_hold * 5))


def main():
    global SERVER_OFFSET
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    try:
        SERVER_OFFSET = measure_offset_hours()
        m5 = fetch_vol_bars(mt5.TIMEFRAME_M5, M5_FETCH)
        h1 = fetch_vol_bars(mt5.TIMEFRAME_H1, H1_FETCH)
    finally:
        mt5.shutdown()

    print("=" * 66)
    print("SCALP M5 session-break micro-scalp -- fixed vs trail, "
          "cost-aware, 200 days")
    print("=" * 66)
    print("M5 fetched %d (requested %d) | trade window: last %d bars "
          "(warmup %d)" % (len(m5), M5_FETCH, M5_TRADE_BARS, M5_WARMUP))
    if len(m5) < M5_FETCH:
        print("WARNING: M5 history shallower than requested -- "
              "window trimmed to %d bars" % (len(m5) - M5_WARMUP))
    if len(h1) < H1_FETCH:
        print("WARNING: H1 fetched only %d" % len(h1))
    w0, w1 = m5[M5_WARMUP]["time"], m5[-1]["time"]
    print("window UTC: %s .. %s"
          % (datetime.utcfromtimestamp(w0), datetime.utcfromtimestamp(w1)))
    print("H1 fetched %d | first H1 %s (covers window start: %s)"
          % (len(h1), datetime.utcfromtimestamp(h1[0]["time"]),
             h1[0]["time"] < w0))
    print("server offset from live tick: UTC%+d (bar epochs are "
          "server-wall)" % SERVER_OFFSET)
    top = activity_profile(m5)
    print("top server-hours by tick vol: %s -> UTC %s"
          % ([h for h, _ in top],
             [((h - SERVER_OFFSET) % 24) for h, _ in top]))

    h1_times = [b["time"] for b in h1]
    h1_trs = bae.tr_series(h1)
    bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = \
        TRAIL_ACT, TRAIL_DIST, TRAIL_STEP

    for mode, label in (
        ("utc", "A: windows in UTC (London 07-10, NY 13:30-16:30 UTC) "
                "-- PRIMARY"),
        ("server", "B: literal broker-wall windows (07-10, 13:30-16:30 "
                   "server = 04-07, 10:30-13:30 UTC)"),
    ):
        print()
        print("=" * 66)
        print("Interpretation %s" % label)
        print("=" * 66)
        events = gen_events(m5, h1_times, h1_trs, mode)
        for trailing, arm in ((False, "FIXED"), (True, "TRAIL")):
            trades, rej = run_events(events, m5, trailing, COST_BASE)
            report("%s arm" % arm, events, trades, rej)

    print()
    print("NOTE: trail arm uses bae.walk_exit_trail with a = signal-time "
          "H1 ATR (0.4-ATR stop aware), view truncated to the 9-bar "
          "hold window; fixed arm = walk_timed SL-before-TP with the "
          "same time stop. Cost deducted per round trip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
