"""Backtest the XAUUSD SmartMoney+VolumeProfile (SMVP) EA logic.

A faithful port of XAUUSD_SmartMoney_VolumeProfile_EA.mq5 to bar-replay:
  - entries evaluated on each closed M1 candle (the EA's IsNewBar/shift-1 rules)
  - M5 EMA20/50 trend filter + M5 close beyond the fast EMA
  - demand/supply zones: opposite-color base candle 2..80 bars back followed
    within 3 bars (toward the present) by an impulse >= 1.2*ATR whose close
    passes beyond the base candle's extreme
  - tick-volume POC over 120 bars / 48 bins, confluence within 0.6*ATR
  - confirmation candle: body>=0.35*range, or engulfing, or wick>=0.20 with
    close beyond 60%/40% of the range (the EA's exact three-pattern OR)
  - SL = min(max(1.5*ATR, $2.50), $25) also pushed beyond the zone edge;
    TP = 1.5R
  - break-even at +0.8R (+$0.20), ATR+chandelier(12) trailing from +1.0R,
    min step $0.25 -- SL tested before trail updates (pessimistic, 1-bar lag)
  - one position at a time, max 30 entries/day, Friday >= 20:00 no new entries
  - costs: spread 0.10 + commission 0.04 per round trip, fixed 0.01 lot
    (the EA defaults to 0.5% risk sizing; fixed lot keeps it comparable
    with the FTTest streams)

Usage (VPS): python C:/FTTest/scripts/backtest_smvp.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

SPREAD = 0.10
COMMISSION = 0.04
POINT = 0.01            # XAUUSD 2 digits
MIN_SL = 250 * POINT    # $2.50
MAX_SL = 2500 * POINT   # $25.00
SL_ATR = 1.5
TP_RR = 1.5
ZONE_BUF = 0.15
IMPULSE_ATR = 1.2
BE_TRIGGER_R = 0.80
BE_OFFSET = 20 * POINT
TRAIL_START_R = 1.00
TRAIL_ATR = 1.00
TRAIL_STEP = 25 * POINT
CHAN_LOOKBACK = 12
MAX_TRADES_DAY = 30
FRIDAY_CUTOFF_HOUR = 20
BARS_REQUEST = 30 * 1440 + 2600   # 30d of M1 + warmup


def ema_series(closes, period):
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    e = sum(closes[:period]) / period
    out[period - 1] = e
    k = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def atr_at(bars, i, period=14):
    if i < period:
        return None
    s = 0.0
    for j in range(i - period + 1, i + 1):
        pc = bars[j - 1]["close"]
        s += max(bars[j]["high"] - bars[j]["low"],
                 abs(bars[j]["high"] - pc), abs(bars[j]["low"] - pc))
    return s / period


def find_zone(bars, i, want, a):
    """Zone search ending at closed bar i. Base candle k bars back (2..80);
    an impulse candle between k and i (within 3 bars after the base) with a
    body >= 1.2*ATR closing beyond the base extreme. Mirrors the EA loops
    (its arrays are series; here time runs forward)."""
    for k in range(i - 2, max(i - 80, 0) - 1, -1):
        b = bars[k]
        if want == "demand" and b["close"] >= b["open"]:
            continue
        if want == "supply" and b["close"] <= b["open"]:
            continue
        for j in range(k - 1, max(i - 4, k - 3) - 1, -1):
            c = bars[j]
            if want == "demand":
                if c["close"] > c["open"] and (c["close"] - c["open"]) >= a * IMPULSE_ATR \
                        and c["close"] > b["high"]:
                    return (b["low"], max(b["open"], b["close"]))
            else:
                if c["close"] < c["open"] and (c["open"] - c["close"]) >= a * IMPULSE_ATR \
                        and c["close"] < b["low"]:
                    return (min(b["open"], b["close"]), b["high"])
    return None


def find_poc(bars, i, lookback=120, bins=48):
    seg = bars[max(0, i - lookback):i + 1]
    if len(seg) < 20:
        return None
    lo = min(b["low"] for b in seg)
    hi = max(b["high"] for b in seg)
    if hi <= lo:
        return None
    vol = [0.0] * bins
    bs = (hi - lo) / bins
    for b in seg:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        vol[max(0, min(bins - 1, int((tp - lo) / bs)))] += b["tick_volume"]
    return lo + (vol.index(max(vol)) + 0.5) * bs


def confirmation(bars, i, want):
    c, p = bars[i], bars[i - 1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body = abs(c["close"] - c["open"])
    if want == "bull":
        lw = min(c["open"], c["close"]) - c["low"]
        return (c["close"] > c["open"] and body / rng >= 0.35) or \
               (c["close"] > c["open"] and p["close"] < p["open"] and
                c["close"] >= p["open"] and c["open"] <= p["close"]) or \
               (c["close"] > c["open"] and lw / rng >= 0.20 and
                c["close"] > (c["low"] + rng * 0.60))
    uw = c["high"] - max(c["open"], c["close"])
    return (c["close"] < c["open"] and body / rng >= 0.35) or \
           (c["close"] < c["open"] and p["close"] > p["open"] and
            c["close"] <= p["open"] and c["open"] >= p["close"]) or \
           (c["close"] < c["open"] and uw / rng >= 0.20 and
            c["close"] < (c["low"] + rng * 0.40))


def main():
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    sym = "XAUUSD"
    mt5.symbol_select(sym, True)
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, BARS_REQUEST)
    if rates is None or len(rates) < 3000:
        print("not enough M1 bars: %s" % (0 if rates is None else len(rates)))
        mt5.shutdown()
        return 1
    bars = [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"],
             "tick_volume": int(r["tick_volume"])} for r in rates]

    # M5 trend series aligned by timestamp (the EA checks the last CLOSED M5)
    m5bars = [{"time": int(r["time"]), "close": r["close"]}
              for r in mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 1,
                                               BARS_REQUEST // 5 + 400)]
    m5closes = [b["close"] for b in m5bars]
    ema_f = ema_series(m5closes, 20)
    ema_s = ema_series(m5closes, 50)

    def m5_trend(ts):
        idx = None
        for k in range(len(m5bars) - 1, -1, -1):
            if m5bars[k]["time"] <= ts:
                idx = k
                break
        if idx is None or ema_f[idx] is None or ema_s[idx] is None:
            return None
        f, s, close = ema_f[idx], ema_s[idx], m5closes[idx]
        if f > s and close > f:
            return "bull"
        if f < s and close < f:
            return "bear"
        return None

    trades = []          # (raw price move, initial risk) per closed trade
    pos = None
    busy_until = -1
    day = None
    trades_today = 0
    span_days = (bars[-1]["time"] - bars[0]["time"]) / 86400.0

    for i in range(300, len(bars)):
        b = bars[i]
        ts = b["time"]
        d = ts // 86400
        if d != day:
            day = d
            trades_today = 0

        # ---------- manage the open position on this bar (BE + trail)
        if pos:
            if pos["side"] == "buy":
                if b["low"] <= pos["sl"]:
                    trades.append((pos["sl"] - pos["entry"], pos["risk"]))
                    pos = None
                    busy_until = i
                elif b["high"] >= pos["tp"]:
                    trades.append((pos["tp"] - pos["entry"], pos["risk"]))
                    pos = None
                    busy_until = i
                else:
                    pr = (b["high"] - pos["entry"]) / pos["risk"]
                    new_sl = pos["sl"]
                    if pr >= BE_TRIGGER_R:
                        new_sl = max(new_sl, pos["entry"] + BE_OFFSET)
                    if pr >= TRAIL_START_R:
                        a = atr_at(bars, i)
                        if a:
                            hi12 = max(x["high"] for x in bars[i - CHAN_LOOKBACK:i + 1])
                            trail = max(b["high"] - a * TRAIL_ATR,
                                        hi12 - a * TRAIL_ATR)
                            if trail >= new_sl + TRAIL_STEP:
                                new_sl = trail
                    if new_sl > pos["sl"]:
                        pos["sl"] = new_sl
            else:
                if b["high"] >= pos["sl"]:
                    trades.append((pos["entry"] - pos["sl"], pos["risk"]))
                    pos = None
                    busy_until = i
                elif b["low"] <= pos["tp"]:
                    trades.append((pos["entry"] - pos["tp"], pos["risk"]))
                    pos = None
                    busy_until = i
                else:
                    pr = (pos["entry"] - b["low"]) / pos["risk"]
                    new_sl = pos["sl"]
                    if pr >= BE_TRIGGER_R:
                        new_sl = min(new_sl, pos["entry"] - BE_OFFSET)
                    if pr >= TRAIL_START_R:
                        a = atr_at(bars, i)
                        if a:
                            lo12 = min(x["low"] for x in bars[i - CHAN_LOOKBACK:i + 1])
                            trail = min(b["low"] + a * TRAIL_ATR,
                                        lo12 + a * TRAIL_ATR)
                            if trail <= new_sl - TRAIL_STEP:
                                new_sl = trail
                    if new_sl < pos["sl"]:
                        pos["sl"] = new_sl
            continue

        if i <= busy_until:
            continue
        # ---------- entry checks (closed-candle rules, like the EA)
        hour = (ts % 86400) // 3600
        dow = (d + 4) % 7          # epoch day 0 = Thursday -> Fri == 4
        if dow == 4 and hour >= FRIDAY_CUTOFF_HOUR:
            continue
        if trades_today >= MAX_TRADES_DAY:
            continue
        a = atr_at(bars, i, 14)
        if not a or a <= 0:
            continue
        trend = m5_trend(ts)
        if trend is None:
            continue
        mid = (b["high"] + b["low"] + b["close"]) / 3.0   # EA uses tick mid
        tol = a * 0.20
        poc = find_poc(bars, i)
        if poc is None:
            continue
        in_poc = abs(mid - poc) <= a * 0.60

        zone = find_zone(bars, i, "demand", a)
        if trend == "bull" and zone and in_poc and \
           zone[0] - tol <= mid <= zone[1] + tol and confirmation(bars, i, "bull"):
            entry = b["close"] + SPREAD / 2.0
            sl = min(entry - max(a * SL_ATR, MIN_SL), zone[0] - a * ZONE_BUF)
            if entry - sl > MAX_SL:
                sl = entry - MAX_SL
            risk = entry - sl
            if risk > 0:
                pos = {"side": "buy", "entry": entry, "sl": sl,
                       "tp": entry + risk * TP_RR, "risk": risk}
                trades_today += 1
            continue

        zone = find_zone(bars, i, "supply", a)
        if trend == "bear" and zone and in_poc and \
           zone[0] - tol <= mid <= zone[1] + tol and confirmation(bars, i, "bear"):
            entry = b["close"] - SPREAD / 2.0
            sl = max(entry + max(a * SL_ATR, MIN_SL), zone[1] + a * ZONE_BUF)
            if sl - entry > MAX_SL:
                sl = entry + MAX_SL
            risk = sl - entry
            if risk > 0:
                pos = {"side": "sell", "entry": entry, "sl": sl,
                       "tp": entry - risk * TP_RR, "risk": risk}
                trades_today += 1

    if pos:
        px = bars[-1]["close"]
        raw = (px - pos["entry"]) if pos["side"] == "buy" else (pos["entry"] - px)
        trades.append((raw, pos["risk"]))

    # ---- sizing modes: fixed 0.01 lot (FTTest-comparable) and the EA's native
    # risk-percent sizing (compounding balance, gold: $100 per $1 move per 1.0
    # lot, commission $4/lot RT, spread $0.10 of price)
    start_bal = acc.balance

    def report(name, mode, pct=0.0):
        if not trades:
            print("  %-14s no trades" % name)
            return
        pnl_list = []
        bal = start_bal
        for raw, risk in trades:
            if mode == "fixed":
                pnl = raw - SPREAD - COMMISSION
            else:
                lots = math.floor((bal * pct / 100.0) / (risk * 100.0) / 0.01) * 0.01
                lots = max(0.01, min(2.0, lots))
                pnl = lots * (100.0 * (raw - SPREAD) - 4.0)
            bal += pnl
            pnl_list.append(pnl)
        wins = [t for t in pnl_list if t > 0]
        losses = [t for t in pnl_list if t <= 0]
        gw, gl = sum(wins), abs(sum(losses))
        pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
        eq = peak = dd = 0.0
        for t in pnl_list:
            eq += t
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        net = sum(pnl_list)
        if mode == "fixed":
            print("  %-14s net=$%7.2f  PF=%s  win%%=%.1f  maxDD=$%.2f"
                  % (name, net, pf, 100.0 * len(wins) / len(pnl_list), dd))
        else:
            print("  %-14s net=$%7.2f  PF=%s  win%%=%.1f  maxDD=$%.2f (%.1f%%)  "
                  "balance $%.0f -> $%.0f (%+.1f%%)"
                  % (name, net, pf, 100.0 * len(wins) / len(pnl_list), dd,
                     100.0 * dd / start_bal, start_bal, bal, 100.0 * net / start_bal))

    print("SMVP EA port -- XAUUSD M1, last %.1f days, %d closed trades, "
          "start balance $%.0f" % (span_days, len(trades), start_bal))
    report("fixed 0.01 lot", "fixed")
    report("risk 0.50%%", "risk", 0.50)    # the EA's native default
    report("risk 0.25%%", "risk", 0.25)    # what will run on the demo chart
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
