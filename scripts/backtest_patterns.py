r"""H1 chart-pattern strategy for XAUUSD -- double bottoms/tops (W/M)
and head-and-shoulders / inverse H&S, neckline-break entries with
measured-move targets, fixed SL/TP vs triple trail, cost-aware.

Pattern rules (all causal -- a swing at bar j is only known once bar
j+2 has closed; every trigger is a CLOSE beyond the neckline):
  * W  double bottom: two swing lows 8-60 bars apart, within 0.4%
       of each other; neckline = highest high between them; pattern
       height 0.5-6x H1 ATR(14); trigger = fresh close above the
       neckline with no close above it since the second low.
       BUY.  SL = lower low - 0.2xATR, TP = neckline + height.
  * M  double top: mirror. SELL.
  * H&S: three swing highs (separations 5-40 bars), middle is the
       head, shoulders within 0.4%, head >= 0.5xATR above the
       shoulders; neckline = mean of the two intervening swing lows;
       trigger = fresh close below it, none below since the right
       shoulder. SELL. SL = head + 0.2xATR, TP = neckline - height.
  * IH&S: mirror. BUY.
  * Volume filter: trigger bar tick volume >= 1.2x its 20-bar median.

Risk manager (house): max 2 concurrent (1 per direction), max 2/day,
1-day (24-bar) cooldown after a loss, 10-bar signal spacing,
5-day (120-bar) hard time stop on BOTH arms so they stay comparable.
Trail arm: house triple 0.05/0.15/0.02 on the signal-time H1 ATR
(same ATR the SL/TP were built from).
Cost $0.24/round-trip (house: 0.20 spread + 0.04 comm); sensitivity
row at $0.35 (IOC slippage). DPU = 1.0 (P&L$ = price delta).
Pessimistic same-bar SL fill on the entry bar (house convention).

Runs ON THE VPS (needs MetaTrader5 + terminal data).
Usage: python C:\FTTest\scripts\backtest_patterns.py
"""
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
from backtest_institutional import walk_timed
from backtest_new_candidates import row

SYMBOL = "XAUUSD"
H1_FETCH = 50000
H1_WARMUP = 300

SL_BUF = 0.2        # ATR buffer beyond the pattern extreme
MIN_H = 0.5         # min pattern height, ATR units
MAX_H = 6.0
TOL = 0.004         # twin tolerance (0.4%)
SEP_W = (8, 60)     # W/M twin separation, bars
SEP_HS = (5, 40)    # H&S shoulder-head separation, bars
VOL_LEN = 20
VOL_MULT = 1.2

TRAIL_ACT, TRAIL_DIST, TRAIL_STEP = 0.05, 0.15, 0.02
TIME_STOP_BARS = 120    # 5 trading days
COOLDOWN_BARS = 24      # 1 day after a loss
MAX_DAY = 2
MAX_CONC = 2
SPACING = 10
COST_BASE = 0.24
COST_SENS = (0.24, 0.35)


# ---------------------------------------------------------------- data
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


# ---------------------------------------------------------------- signals
def gen_events(bars, trs):
    """Detect W/M/H&S/IH&S neckline breaks.  Returns
    (events, detected-shape counts, generation rejects)."""
    n = len(bars)
    sh = [False] * n
    sl = [False] * n
    for i in range(2, n - 2):
        h, l = bars[i]["high"], bars[i]["low"]
        if (h > bars[i - 1]["high"] and h > bars[i - 2]["high"]
                and h >= bars[i + 1]["high"] and h >= bars[i + 2]["high"]):
            sh[i] = True
        if (l < bars[i - 1]["low"] and l < bars[i - 2]["low"]
                and l <= bars[i + 1]["low"] and l <= bars[i + 2]["low"]):
            sl[i] = True
    prev_sh, prev_sl = [-1] * n, [-1] * n
    p = -1
    for k in range(n):
        if sh[k]:
            p = k
        prev_sh[k] = p
    p = -1
    for k in range(n):
        if sl[k]:
            p = k
        prev_sl[k] = p

    detected = {"W": 0, "M": 0, "H&S": 0, "IH&S": 0}
    grej = {"spacing": 0, "vol": 0}
    evs = []
    last_i = -10 ** 9

    for i in range(H1_WARMUP, n - 1):
        if i - last_i < SPACING:
            grej["spacing"] += 1
            continue
        a = bae.sma_atr_at(trs, i, 14)
        if a is None or a <= 0:
            continue
        found = None

        # ---- W: double bottom -> buy
        j2 = prev_sl[i - 2]
        if j2 > 0:
            j1 = prev_sl[j2 - 1]
            if j1 >= 0 and SEP_W[0] <= j2 - j1 <= SEP_W[1]:
                l1, l2 = bars[j1]["low"], bars[j2]["low"]
                lo = min(l1, l2)
                if abs(l1 - l2) <= TOL * lo:
                    nk = max(bars[k]["high"] for k in range(j1 + 1, j2))
                    h = nk - lo
                    if MIN_H * a <= h <= MAX_H * a:
                        detected["W"] += 1
                        seg = [bars[k]["close"] for k in range(j2 + 1, i)]
                        if (all(c <= nk for c in seg)
                                and bars[i]["close"] > nk
                                >= bars[i - 1]["close"]):
                            found = ("W", "buy",
                                     lo - SL_BUF * a, nk + h)

        # ---- M: double top -> sell
        if found is None:
            j2 = prev_sh[i - 2]
            if j2 > 0:
                j1 = prev_sh[j2 - 1]
                if j1 >= 0 and SEP_W[0] <= j2 - j1 <= SEP_W[1]:
                    h1, h2 = bars[j1]["high"], bars[j2]["high"]
                    hi = max(h1, h2)
                    if abs(h1 - h2) <= TOL * hi:
                        nk = min(bars[k]["low"] for k in range(j1 + 1, j2))
                        h = hi - nk
                        if MIN_H * a <= h <= MAX_H * a:
                            detected["M"] += 1
                            seg = [bars[k]["close"] for k in range(j2 + 1, i)]
                            if (all(c >= nk for c in seg)
                                    and bars[i]["close"] < nk
                                    <= bars[i - 1]["close"]):
                                found = ("M", "sell",
                                         hi + SL_BUF * a, nk - h)

        # ---- H&S: three swing highs, head in the middle -> sell
        if found is None:
            j3 = prev_sh[i - 2]
            if j3 > 0:
                j2 = prev_sh[j3 - 1]
                if j2 > 0:
                    j1 = prev_sh[j2 - 1]
                    if (j1 >= 0
                            and SEP_HS[0] <= j2 - j1 <= SEP_HS[1]
                            and SEP_HS[0] <= j3 - j2 <= SEP_HS[1]):
                        s1 = bars[j1]["high"]
                        hd = bars[j2]["high"]
                        s2 = bars[j3]["high"]
                        if (hd > s1 and hd > s2
                                and abs(s1 - s2) <= TOL * min(s1, s2)):
                            la = prev_sl[j2 - 1]
                            lb = prev_sl[j3 - 1]
                            if la > j1 and lb > j2:
                                nk = (bars[la]["low"] + bars[lb]["low"]) / 2.0
                                h = hd - nk
                                if MIN_H * a <= h <= MAX_H * a:
                                    detected["H&S"] += 1
                                    seg = [bars[k]["close"]
                                           for k in range(j3 + 1, i)]
                                    if (all(c >= nk for c in seg)
                                            and bars[i]["close"] < nk
                                            <= bars[i - 1]["close"]):
                                        found = ("H&S", "sell",
                                                 hd + SL_BUF * a, nk - h)

        # ---- IH&S: three swing lows, head in the middle -> buy
        if found is None:
            j3 = prev_sl[i - 2]
            if j3 > 0:
                j2 = prev_sl[j3 - 1]
                if j2 > 0:
                    j1 = prev_sl[j2 - 1]
                    if (j1 >= 0
                            and SEP_HS[0] <= j2 - j1 <= SEP_HS[1]
                            and SEP_HS[0] <= j3 - j2 <= SEP_HS[1]):
                        s1 = bars[j1]["low"]
                        hd = bars[j2]["low"]
                        s2 = bars[j3]["low"]
                        if (hd < s1 and hd < s2
                                and abs(s1 - s2) <= TOL * min(s1, s2)):
                            ha = prev_sh[j2 - 1]
                            hb = prev_sh[j3 - 1]
                            if ha > j1 and hb > j2:
                                nk = (bars[ha]["high"] + bars[hb]["high"]) / 2.0
                                h = nk - hd
                                if MIN_H * a <= h <= MAX_H * a:
                                    detected["IH&S"] += 1
                                    seg = [bars[k]["close"]
                                           for k in range(j3 + 1, i)]
                                    if (all(c <= nk for c in seg)
                                            and bars[i]["close"] > nk
                                            >= bars[i - 1]["close"]):
                                        found = ("IH&S", "buy",
                                                 hd - SL_BUF * a, nk + h)

        if found is None:
            continue
        med = statistics.median([bars[k]["vol"] for k in range(i - VOL_LEN, i)])
        if med <= 0 or bars[i]["vol"] < VOL_MULT * med:
            grej["vol"] += 1
            continue
        pat, side, sl, tp = found
        evs.append({"i": i, "side": side, "sl": sl, "tp": tp,
                    "a": a, "pat": pat, "day": bars[i]["time"] // 86400})
        last_i = i
    return evs, detected, grej


# ---------------------------------------------------------------- runner
def run_events(events, bars, trailing):
    """Shared risk manager: max 2 concurrent (1/direction), 24-bar
    loss cooldown, 2 trades/day.  Returns (trades, stats)."""
    trades = []                      # (raw, pat, day, hold, a, sl, tp, entry)
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
            view = bars[:start + TIME_STOP_BARS - 1]
            if trailing:
                px, ex_i, _ = bae.walk_exit_trail(
                    ev["side"], entry, sl, tp, a, view, start)
            else:
                px, ex_i = walk_timed(ev["side"], sl, tp, view, start,
                                      TIME_STOP_BARS - 1)
            raw = (px - entry) if ev["side"] == "buy" else (entry - px)
        trades.append((raw, ev["pat"], ev["day"], ex_i - i, a,
                       sl, tp, entry))
        day_n[ev["day"]] = day_n.get(ev["day"], 0) + 1
        open_t = [t for t in open_t if t[1] >= i + 1]
        open_t.append((ev["side"], ex_i))
        if raw <= 0:
            cool = ex_i + COOLDOWN_BARS
    return trades, rej


# ---------------------------------------------------------------- report
def fmt_row(n, net, pf, win):
    return "%5d %+10.2f %8s %6.1f%% %+8.2f" % (
        n, net, pf, win, (net / n) if n else 0.0)


def stats(trades, cost):
    nets = [t[0] - cost for t in trades]
    n, net, pf, win = row(nets)
    return {"n": n, "net": net, "pf": pf, "win": win}


def report(name, events, trades, rej, grej, detected):
    print("--- %s ---" % name)
    print("signals: %d generated | %d accepted | rejects: spacing %d, "
          "volume %d, cooldown %d, day-cap %d, concurrency %d"
          % (len(events), len(trades), grej["spacing"], grej["vol"],
             rej["cool"], rej["day"], rej["conc"]))
    if not trades:
        print("NO TRADES")
        return
    atrs = [t[4] for t in trades]
    # SL distance in price terms (risk of one trade);
    # W/IH&S are buys, M/H&S are sells
    risks = []
    for t in trades:
        sl, entry = t[5], t[7]
        risks.append((entry - sl) if t[1] in ("W", "IH&S")
                     else (sl - entry))
    avg_r = sum(risks) / len(risks) if risks else 0.0
    print("avg signal-time H1 ATR(14): $%.2f | avg SL distance $%.2f "
          "(~%.2f ATR)"
          % (sum(atrs) / len(atrs), avg_r,
             avg_r / (sum(atrs) / len(atrs))))
    for cost in COST_SENS:
        s = stats(trades, cost)
        print("cost $%.2f: %s   (n net PF win%%/per-trip)"
              % (cost, fmt_row(s["n"], s["net"], s["pf"], s["win"])))
    s = stats(trades, COST_BASE)
    for pat in ("W", "M", "H&S", "IH&S"):
        st = [t for t in trades if t[1] == pat]
        ss = stats(st, COST_BASE)
        print("  %-5s shapes %4d | %s"
              % (pat, detected.get(pat, 0),
                 fmt_row(ss["n"], ss["net"], ss["pf"], ss["win"])))
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
    print("  worst trade $%.2f | avg hold %.0f bars (~%.1f days)"
          % (worst, avg_hold, avg_hold / 24.0))


def main():
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    try:
        off = measure_offset_hours()
        h1 = fetch_vol_bars(mt5.TIMEFRAME_H1, H1_FETCH)
    finally:
        mt5.shutdown()

    print("=" * 66)
    print("XAUUSD H1 chart patterns -- W/M + H&S/IH&S, fixed vs trail")
    print("=" * 66)
    print("H1 fetched %d (requested %d) | trade window: last %d bars "
          "(warmup %d)" % (len(h1), H1_FETCH,
                           len(h1) - H1_WARMUP, H1_WARMUP))
    if len(h1) < H1_WARMUP + 1000:
        print("WARNING: H1 history too shallow -- aborting")
        return 1
    print("window UTC: %s .. %s"
          % (datetime.utcfromtimestamp(h1[H1_WARMUP]["time"]),
             datetime.utcfromtimestamp(h1[-1]["time"])))
    print("server offset from live tick: %s"
          % ("UTC%+d" % off if off is not None else "n/a"))
    trs = bae.tr_series(h1)
    atrs = [bae.sma_atr_at(trs, i, 14)
            for i in range(H1_WARMUP, len(h1))]
    atrs = [x for x in atrs if x and x > 0]
    print("avg H1 ATR(14) over window: $%.2f" % (sum(atrs) / len(atrs)))

    bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = \
        TRAIL_ACT, TRAIL_DIST, TRAIL_STEP
    events, detected, grej = gen_events(h1, trs)
    print("pattern shapes detected (pre-trigger, spaced bars): %s"
          % detected)
    for trailing, label in ((False, "FIXED"), (True, "TRAIL")):
        trades, rej = run_events(events, h1, trailing)
        report(label, events, trades, rej, grej, detected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
