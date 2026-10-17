r"""Backtest the profile + orderflow FTTest EAs over a configurable window.

Faithful bar-replay ports of the two new signal engines (mql5/FTTestCore.mqh):
  - signals evaluated on each CLOSED bar; entry at the NEXT bar's open
  - PROFILE (FTTest_profile, M15): TPO histogram over the last InpProfileBars
    closed bars, body-time per bin, POC + 70% value area; breakout beyond
    VA edge +/- 0.5 ATR (SL 1.5 ATR / TP 3 ATR) or rotation back to the POC
    (SL 1.2 ATR / TP = POC)
  - ORDERFLOW (FTTest_orderflow, M1): per-minute flow buckets. Live the EA
    uses tick flags / the tick rule on real ticks; the backtest has no tick
    history on a retail MT5 server, so flow is SYNTHESIZED from the M1 bar:
    close-location-value (CLV) fraction of (high+low+2*close)/4 shifted by
    the previous close, times volume. This models delta direction well but
    smooths intrabar spikes -- treat imbalance-trade counts as optimistic
    approximations of the live EA's tick-rule counts.
    Entries: absorption (wide bar, wick > 2x body, close back in rejection
    direction, cumulative flow aligned; 1:2 R:R) and delta imbalance
    (delta[0] >= 3x |delta[1]|, prior opposite, cumulative aligned and
    >= 60% of two-way volume; SL 1 ATR / TP 2 ATR)
  - twins: fixed (static SL/TP) vs trailing (activate +1.0 ATR, distance
    1.2 ATR, step 0.3 ATR -- the FTTest -T twin rule); pessimistic
    intrabar ordering: SL tested before trail updates
  - costs per round trip: broker spread (below) + $0.04 commission at 0.01 lot
  - one position at a time per stream; the EA would reverse on an opposite
    signal, the harness (like all our backtests) holds until SL/TP instead

Usage (VPS): python C:/FTTest/scripts/backtest_profile_orderflow.py
             [--symbol XAUUSD] [--days 90]
Profile runs on M15, orderflow on M1 (exactly like charts 21-24).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

COMMISSION = 0.04
SPREAD_PRICE = {"XAUUSD": 0.20, "EURUSD": 0.00015, "GBPUSD": 0.00020,
                "USDJPY": 0.015, "AUDUSD": 0.00020}
TRAIL_ACTIVATE, TRAIL_DIST, TRAIL_STEP = 1.0, 1.2, 0.3

# profile engine constants (FTTestCore defaults)
PROF_BARS, PROF_BINS, VA_PCT = 96, 24, 70.0
PROF_BRK_SL, PROF_BRK_TP, PROF_BUF = 1.5, 3.0, 0.5
PROF_ROT_SL = 1.2

# orderflow engine constants
OF_WINDOW = 30          # minutes
OF_IMB = 3.0            # delta imbalance ratio
OF_MIN_CUM = 0.6        # min cumulative-delta share
OF_ABS_RANGE = 0.8      # wide bar: range >= x ATR
OF_ABS_WICK = 2.0       # wick >= x body
WARMUP_M1 = OF_WINDOW + 16
WARMUP_M15 = PROF_BARS + 20


def atr_at(bars, i, period=14):
    """SMA of TR over `period` bars ending at i (bars = tuple list)."""
    if i < period:
        return None
    s = 0.0
    for j in range(i - period + 1, i + 1):
        pc = bars[j - 1][4]
        s += max(bars[j][2] - bars[j][3],
                 abs(bars[j][2] - pc), abs(bars[j][3] - pc))
    return s / period


# ----------------------------------------------------------------- profile

def market_profile(bars, i0, i1, bins):
    """TPO histogram over bars[i0:i1]; returns (poc, vah, val) or None."""
    lo = min(b[3] for b in bars[i0:i1])
    hi = max(b[2] for b in bars[i0:i1])
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    tpo = [0] * bins
    for b in bars[i0:i1]:
        bl, bh = (b[0], b[1]) if b[0] <= b[1] else (b[1], b[0])  # body (o,c)
        if bh <= bl:
            bh = bl + step
        j0 = max(0, int((bl - lo) / step))
        j1 = min(bins - 1, int((bh - lo) / step))
        for j in range(j0, j1 + 1):
            tpo[j] += 1
    total = sum(tpo)
    poc = max(range(bins), key=lambda j: tpo[j])
    if total <= 0 or tpo[poc] <= 0:
        return None
    need = total * VA_PCT / 100.0
    loI = hiI = poc
    covered = tpo[poc]
    while covered < need and (loI > 0 or hiI < bins - 1):
        dn = tpo[loI - 1] if loI > 0 else -1
        up = tpo[hiI + 1] if hiI < bins - 1 else -1
        if dn < 0 and up < 0:
            break
        if up >= dn:
            hiI += 1
            covered += up
        else:
            loI -= 1
            covered += dn
    return lo + (poc + 0.5) * step, lo + (hiI + 1.0) * step, lo + loI * step


def signal_profile(bars, i):
    """'buy'/'sell' or None, with (sl, tp) -- mirrors SigProfile."""
    a = atr_at(bars, i)
    if not a or a <= 0:
        return None
    prof = market_profile(bars, i + 1 - PROF_BARS, i + 1, PROF_BINS)
    if prof is None:
        return None
    poc, vah, val = prof
    c = bars[i][4]
    if c > vah + PROF_BUF * a:
        return ("buy", c - PROF_BRK_SL * a, c + PROF_BRK_TP * a)
    if c < val - PROF_BUF * a:
        return ("sell", c + PROF_BRK_SL * a, c - PROF_BRK_TP * a)
    if c > vah:
        return ("sell", c + PROF_ROT_SL * a, poc)
    if c < val:
        return ("buy", c - PROF_ROT_SL * a, poc)
    return None


# --------------------------------------------------------------- orderflow

def flow_buckets(bars, i, window):
    """Synthetic per-minute delta for the `window` closed minutes ending at
    bar i (index window-1 = the newest closed minute). CLV-based."""
    delta = [0.0] * window
    prev_close = bars[i - window][4]
    for k in range(window):
        b = bars[i - window + 1 + k]
        rng = b[2] - b[3]
        # CLV: where the close sits in the bar's range (-1..+1)
        clv = ((2.0 * b[4] - b[2] - b[3]) / rng) if rng > 0 else 0.0
        # tilt by gap vs previous close so flat-range bars still get direction
        tilt = 0.0
        if prev_close:
            tilt = max(-0.5, min(0.5, (b[4] - prev_close) / max(rng, 1e-9)))
        delta[k] = (clv + tilt) * max(b[5], 1.0)
        prev_close = b[4]
    return delta


def signal_orderflow(bars, i):
    """'buy'/'sell' or None with (sl, tp) -- mirrors SigOrderflow on M1."""
    a = atr_at(bars, i)
    if not a or a <= 0:
        return None
    delta = flow_buckets(bars, i, OF_WINDOW)
    cum = sum(delta)
    abs_sum = sum(abs(d) for d in delta)
    if abs_sum <= 0:
        return None
    t, o, h, l, c, _v = bars[i]
    rng = h - l
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    wide = rng > OF_ABS_RANGE * a
    # absorption
    if wide and lower_wick > OF_ABS_WICK * body and c >= l + 2.0 * rng / 3.0 and cum >= 0:
        sl = l - 0.2 * a
        return ("buy", sl, c + 2.0 * (c - sl))
    if wide and upper_wick > OF_ABS_WICK * body and c <= l + rng / 3.0 and cum <= 0:
        sl = h + 0.2 * a
        return ("sell", sl, c - 2.0 * (sl - c))
    # delta imbalance: closed minute vs the one before, cumulative aligned
    d0, d1 = delta[-1], delta[-2]
    share = abs(cum) / abs_sum
    if d0 >= OF_IMB * abs(d1) and d1 < 0 and cum > 0 and share >= OF_MIN_CUM:
        return ("buy", c - 1.0 * a, c + 2.0 * a)
    if -d0 >= OF_IMB * abs(d1) and d1 > 0 and cum < 0 and share >= OF_MIN_CUM:
        return ("sell", c + 1.0 * a, c - 2.0 * a)
    return None


# ------------------------------------------------------------------- exits

def walk_exit_fixed(side, sl, tp, bars, start_i):
    for j in range(start_i, len(bars)):
        b = bars[j]
        if side == "buy":
            if b[3] <= sl:
                return sl, j
            if b[2] >= tp:
                return tp, j
        else:
            if b[2] >= sl:
                return sl, j
            if b[3] <= tp:
                return tp, j
    return bars[-1][4], len(bars) - 1


def walk_exit_trail(side, entry, sl, tp, a, bars, start_i):
    cur_sl = sl
    best = None
    for j in range(start_i, len(bars)):
        b = bars[j]
        if side == "buy" and b[3] <= cur_sl:
            return cur_sl, j
        if side == "sell" and b[2] >= cur_sl:
            return cur_sl, j
        if side == "buy":
            if b[2] - entry >= TRAIL_ACTIVATE * a:
                best = max(best, b[2]) if best else b[2]
                new_sl = best - TRAIL_DIST * a
                if new_sl > cur_sl + TRAIL_STEP * a:
                    cur_sl = new_sl
            if b[2] >= tp:
                return tp, j
        else:
            if entry - b[3] >= TRAIL_ACTIVATE * a:
                best = min(best, b[3]) if best else b[3]
                new_sl = best + TRAIL_DIST * a
                if cur_sl == 0 or new_sl < cur_sl - TRAIL_STEP * a:
                    cur_sl = new_sl
            if b[3] <= tp:
                return tp, j
    return bars[-1][4], len(bars) - 1


def run_wrapped(bars, sig_fn, warmup, dpu, cost, trailing):
    """run() but captures the signal-time ATR for the trailing walk (the EA
    trails with the ATR of the signal bar, like FTTestCore's g_atr)."""
    global sig_a
    trades = []
    busy_until = -1
    for i in range(warmup, len(bars) - 2):
        if i <= busy_until:
            continue
        sig = sig_fn(bars, i)
        if sig is None:
            continue
        side, sl, tp = sig
        sig_a = atr_at(bars, i)
        entry = bars[i + 1][1]  # next bar's open
        if (side == "buy" and bars[i + 1][3] <= sl) or \
           (side == "sell" and bars[i + 1][2] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            trades.append(raw * dpu - cost)
            busy_until = i + 1
            continue
        if trailing:
            exit_px, exit_i = walk_exit_trail(side, entry, sl, tp, sig_a, bars, i + 2)
        else:
            exit_px, exit_i = walk_exit_fixed(side, sl, tp, bars, i + 2)
        raw = (exit_px - entry) if side == "buy" else (entry - exit_px)
        trades.append(raw * dpu - cost)
        busy_until = exit_i
    return trades


def row(trades):
    if not trades:
        return (0, 0.0, "n/a")
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
    return (len(trades), sum(trades), pf)


def fetch(symbol, tf, n):
    tfs = {"M1": mt5.TIMEFRAME_M1, "M15": mt5.TIMEFRAME_M15}
    rates = mt5.copy_rates_from_pos(symbol, tfs[tf], 1, n)
    if rates is None:
        return []
    return [(int(r["time"]), r["open"], r["high"], r["low"], r["close"],
             float(r["tick_volume"])) for r in rates]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    symbols = [args.symbol] if args.symbol else \
        ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    days = args.days

    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    print("account %s %s (demo ok)" % (acc.login, acc.server))
    print("[%dd] profile=M15(TPO %db/%dbins/VA%.0f%%)  orderflow=M1(%dmin window, "
          "CLV-synthesized flow) | costs = spread + $0.04 | twins fixed vs trail"
          % (days, PROF_BARS, PROF_BINS, VA_PCT, OF_WINDOW))
    print("%-8s %-10s %18s %18s %s" %
          ("SYMBOL", "ENGINE", "FIXED n/net/PF", "TRAIL n/net/PF", "WINNER"))
    verdicts = {}
    for s in symbols:
        mt5.symbol_select(s, True)
        si = mt5.symbol_info(s)
        if si is None:
            print("%-8s unavailable" % s)
            continue
        dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
        cost = SPREAD_PRICE.get(s, 0.0) * dpu + COMMISSION

        # profile on M15
        bars15 = fetch(s, "M15", days * 96 + PROF_BARS + 60)
        if len(bars15) > WARMUP_M15 + 10:
            fx = run_wrapped(bars15, signal_profile, WARMUP_M15, dpu, cost, False)
            tx = run_wrapped(bars15, signal_profile, WARMUP_M15, dpu, cost, True)
            rf, rt = row(fx), row(tx)
            win = "trail" if rt[1] > rf[1] else "fixed"
            verdicts[(s, "profile")] = win
            print("%-8s %-10s %5d %8.2f %-5s %5d %8.2f %-5s %-6s"
                  % (s, "profile", rf[0], rf[1], rf[2], rt[0], rt[1], rt[2], win))
        else:
            print("%-8s %-10s not enough M15 bars (%d)" % (s, "profile", len(bars15)))

        # orderflow on M1
        bars1 = fetch(s, "M1", days * 1440 + 400)
        if len(bars1) > WARMUP_M1 + 10:
            fx = run_wrapped(bars1, signal_orderflow, WARMUP_M1, dpu, cost, False)
            tx = run_wrapped(bars1, signal_orderflow, WARMUP_M1, dpu, cost, True)
            rf, rt = row(fx), row(tx)
            win = "trail" if rt[1] > rf[1] else "fixed"
            verdicts[(s, "orderflow")] = win
            print("%-8s %-10s %5d %8.2f %-5s %5d %8.2f %-5s %-6s"
                  % (s, "orderflow", rf[0], rf[1], rf[2], rt[0], rt[1], rt[2], win))
        else:
            print("%-8s %-10s not enough M1 bars (%d)" % (s, "orderflow", len(bars1)))
    print("\nsummary verdicts (relative A/B; absolute results matter too):")
    for k in sorted(verdicts):
        print("  %-8s %-10s -> %s" % (k[0], k[1], verdicts[k]))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
