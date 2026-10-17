"""One-off XAUUSD pattern-mining scan (2026-10-01 user request).

Data: M15 (last 180 days), H1 (last 360 days), D1 (last ~3 years) straight
from MT5 via closed_bars(). All analysis UTC; server time ignored entirely.

Hypotheses tested (with house honesty rules: only closed-bar info, report n,
flag small samples, no claims without effect + significance):

  1. HOUR-OF-DAY: mean |return| by UTC hour (when is gold active) and
     directional drift (is there a tradable bias per hour).
  2. DAY-OF-WEEK drift.
  3. AUTOCORRELATION: do returns cluster -- and the doji/tail probe: when the
     M15 range collapses below half its 24-bar median (energy compression),
     what happens next 4 bars / 12 bars (the classic expansion trade)?
  4. GAP STUDY on D1: does Friday-close -> Monday-open gap direction predict
     the Monday session (institutions rebalance into the weekend)?
  5. 20d ROLLING VOL REGIME: compare returns in low-vol vs high-vol tercile
     regimes (when do trend systems work).
  6. BIG-MOVE follow-through: after any D1 move >= 2% or M15 move >= 1.5 ATR,
     what does the NEXT bar/day do (momentum vs mean-reversion)?

Output: a single text report with tables and a SIGNIFICANCE line per stat.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import load_env, closed_bars

OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


def p5(sig, mean, n):
    """Rough significance tag: |t| ~ |mean| * sqrt(n) / stdev proxy."""
    if n < 8:
        return "n=%d (too few)" % n
    z = abs(mean) * (n ** 0.5)
    return "z~%.1f, n=%d %s" % (z, n, "<-- SIGNAL" if z >= 2.0 else "")


def main():
    load_env()
    if not mt5.initialize():
        print("mt5 attach failed")
        return 1
    acc = mt5.account_info()
    emit("pattern scan on %s (%s), demo ok" % (acc.login, acc.server))
    m15 = closed_bars("XAUUSD", "M15", 180 * 96 + 50)
    h1 = closed_bars("XAUUSD", "H1", 360 * 24 + 50)
    d1 = closed_bars("XAUUSD", "D1", 800)
    mt5.shutdown()
    emit("bars: M15 %d | H1 %d | D1 %d" % (len(m15), len(h1), len(d1)))

    # ---------- 1. hour-of-day -------------------------------------------
    # ret of a bar = close-to-close in ATR(96) units to normalize regimes
    def atr_series(bars, n):
        trs = []
        pc = None
        for b in bars:
            ref = pc if pc is not None else b["close"]
            trs.append(max(b["high"] - b["low"],
                           abs(b["high"] - ref),
                           abs(b["low"] - ref)))
            pc = b["close"]
        # rolling mean ATR
        out = [None] * len(trs)
        s = 0.0
        for i, tr in enumerate(trs):
            s += tr
            if i >= n:
                s -= trs[i - n]
            if i >= n - 1:
                out[i] = s / n
        return out

    def hour_atr(bars):
        return atr_series(bars, 96)

    a15 = hour_atr(m15)
    emit("")
    emit("== 1. HOUR-OF-DAY (M15, 180d; ret in ATR units) ==")
    emit("%-5s %8s %8s %8s %8s" % ("UTC", "mean|ret|", "drift", "n", "sig"))
    h_abs = defaultdict(list)
    h_dir = defaultdict(list)
    for i in range(1, len(m15)):
        if a15[i] is None or a15[i - 1] is None:
            continue
        r = (m15[i]["close"] - m15[i - 1]["close"]) / a15[i - 1]
        h = (m15[i]["time"] % 86400) // 3600
        h_abs[h].append(abs(r))
        h_dir[h].append(r)
    hour_rows = []
    for h in range(24):
        if len(h_abs[h]) < 50:
            continue
        ma = sum(h_abs[h]) / len(h_abs[h])
        md = sum(h_dir[h]) / len(h_dir[h])
        hour_rows.append((ma, md, h, len(h_abs[h])))
    hour_rows.sort(reverse=True)
    for ma, md, h, n in hour_rows:
        emit("%02d:00 %8.3f %+8.3f %8d %s" % (h, ma, md, n, p5(None, md, n)))

    # ---------- 2. day-of-week -------------------------------------------
    emit("")
    emit("== 2. DAY-OF-WEEK (D1, ~3y) ==")
    dow_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    dow = defaultdict(list)
    for i in range(1, len(d1)):
        r = (d1[i]["close"] - d1[i - 1]["close"]) / max(d1[i - 1]["close"], 1e-9)
        import time as _t
        wd = _t.gmtime(d1[i]["time"]).tm_wday
        dow[wd].append(r)
    for wd in range(5):
        rs = dow.get(wd, [])
        if not rs:
            continue
        m = sum(rs) / len(rs)
        sd = (sum((x - m) ** 2 for x in rs) / max(1, len(rs) - 1)) ** 0.5
        t = m / sd * (len(rs) ** 0.5) if sd else 0
        emit("%-4s %+7.4f%%  n=%3d  t=%+.2f %s"
             % (dow_names[wd], 100 * m, len(rs), t,
                "<-- SIGNAL" if abs(t) >= 2 and len(rs) >= 40 else ""))

    # ---------- 3. compression -> expansion (doji/tail probe) ------------
    emit("")
    emit("== 3. COMPRESSION -> EXPANSION (M15) ==")
    rng = [b["high"] - b["low"] for b in m15]
    med24 = [None] * len(m15)
    for i in range(24, len(m15)):
        w = sorted(rng[i - 24:i])
        med24[i] = w[12]
    fwd4, fwd12 = defaultdict(list), defaultdict(list)
    for i in range(48, len(m15) - 13):
        if med24[i] is None or a15[i] is None:
            continue
        if rng[i] < 0.5 * med24[i]:
            # direction of the NEXT 4/12 bars (expansion direction bet)
            d4 = (m15[i + 4]["close"] - m15[i]["close"]) / a15[i]
            d12 = (m15[i + 12]["close"] - m15[i]["close"]) / a15[i]
            # also: is there an expansion at all?
            ex = (m15[i + 4]["high"] - m15[i + 4]["low"]) / max(rng[i], 1e-9)
            fwd4[("dir", )].append(d4)
            fwd12[("dir", )].append(d12)
            fwd4[("exp", )].append(ex)
    if fwd4.get(("dir", )):
        d4 = fwd4[("dir", )]
        d12 = fwd12[("dir", )]
        ex = fwd4[("exp", )]
        n = len(d4)
        emit("compression bars (rng < 0.5x median24): n=%d" % n)
        emit("  next-4-bar  drift %+0.3f ATR | %s" % (sum(d4) / n, p5(None, sum(d4) / n, n)))
        emit("  next-12-bar drift %+0.3f ATR | %s" % (sum(d12) / n, p5(None, sum(d12) / n, n)))
        emit("  range expansion x%.2f within 4 bars" % (sum(ex) / n))
        up = sum(1 for x in d12 if x > 0)
        emit("  next-12-bar UP rate: %.1f%% (direction is a coin flip if ~50%%)"
             % (100.0 * up / n))

    # ---------- 4. weekend gap study (D1) --------------------------------
    emit("")
    emit("== 4. WEEKEND GAP STUDY (D1 ~3y) ==")
    import time as _t2
    gaps = []
    for i in range(1, len(d1)):
        w0 = _t2.gmtime(d1[i - 1]["time"]).tm_wday
        w1 = _t2.gmtime(d1[i]["time"]).tm_wday
        if w0 in (4, ) and w1 in (0, ):        # Friday -> Monday
            gap = d1[i]["open"] - d1[i - 1]["close"]
            sess = d1[i]["close"] - d1[i]["open"]
            dayr = d1[i]["close"] - d1[i - 1]["close"]
            gaps.append((gap, sess, dayr))
    if gaps:
        n = len(gaps)
        g = [x[0] for x in gaps]
        s = [x[1] for x in gaps]
        follow = sum(1 for gap, sess, _ in gaps if (gap > 0) == (sess > 0) and sess != 0)
        gm = sum(g) / n
        emit("weekend gaps: n=%d, mean gap %+.2f USD" % (n, gm))
        emit("  Monday session continues gap direction: %d/%d = %.0f%%"
             % (follow, n, 100.0 * follow / n))
        # gap size vs follow-through
        big = [(gap, sess) for gap, sess, _ in gaps if abs(gap) > 2.0]
        if big:
            fb = sum(1 for gap, sess in big if (gap > 0) == (sess > 0) and sess != 0)
            emit("  gaps > $2: n=%d, follow-through %.0f%%"
                 % (len(big), 100.0 * fb / len(big)))

    # ---------- 5. volatility regime vs directional edge ------------------
    emit("")
    emit("== 5. VOL REGIME (D1, 20d rolling, terciles) ==")
    dret = [(d1[i]["close"] - d1[i - 1]["close"]) / d1[i - 1]["close"]
            for i in range(1, len(d1))]
    dvol = []
    for i in range(21, len(dret) + 1):
        w = dret[i - 21:i]
        m = sum(w) / len(w)
        sd = (sum((x - m) ** 2 for x in w) / (len(w) - 1)) ** 0.5
        dvol.append(sd)
    if len(dvol) > 60:
        srt = sorted(dvol)
        lo, hi = srt[len(srt) // 3], srt[2 * len(srt) // 3]
        buckets = {"low": [], "mid": [], "high": []}
        for j, sd in enumerate(dvol):
            r = dret[j + 20]                    # next day's return
            k = "low" if sd <= lo else ("high" if sd >= hi else "mid")
            buckets[k].append(r)
        for k in ("low", "mid", "high"):
            rs = buckets[k]
            m = sum(rs) / len(rs)
            sd = (sum((x - m) ** 2 for x in rs) / max(1, len(rs) - 1)) ** 0.5
            t = m / sd * (len(rs) ** 0.5) if sd else 0
            # |r| tells activity
            ma = sum(abs(x) for x in rs) / len(rs)
            emit("%-4s vol: next-day mean %+0.4f%%  |r| %.3f%%  t=%+.2f  n=%d %s"
                 % (k, 100 * m, 100 * ma, t, len(rs),
                    "<-- SIGNAL" if abs(t) >= 2 and len(rs) >= 60 else ""))

    # ---------- 6. big-move follow-through --------------------------------
    emit("")
    emit("== 6. BIG-MOVE FOLLOW-THROUGH ==")
    # D1: |ret| >= 2%
    bigd = [r for r in dret if abs(r) >= 0.02]
    emit("D1 moves >= 2%%: n=%d" % len(bigd))
    idxs = [i for i, r in enumerate(dret) if abs(r) >= 0.02 and i + 1 < len(dret)]
    nxt = [dret[i + 1] for i in idxs]
    same = sum(1 for i in idxs if (dret[i] > 0) == (dret[i + 1] > 0) and dret[i + 1] != 0)
    if nxt:
        emit("  next-day SAME direction: %d/%d = %.0f%% (momentum if >55, revert if <45)"
             % (same, len(nxt), 100.0 * same / len(nxt)))
        emit("  next-day mean %+.3f%% | %s" % (100 * sum(nxt) / len(nxt),
                                               p5(None, sum(nxt) / len(nxt), len(nxt))))
    # M15: |ret| >= 1.5 ATR -- build index+next list in ONE pass (no zip)
    idxs15, nxt15 = [], []
    for i in range(1, len(m15) - 2):
        if not a15[i - 1] or not a15[i]:
            continue
        move = m15[i]["close"] - m15[i - 1]["close"]
        if abs(move) >= 1.5 * a15[i - 1]:
            idxs15.append(i)
            nxt15.append((m15[i + 1]["close"] - m15[i]["close"]) / a15[i])
    same15 = sum(1 for i, x in zip(idxs15, nxt15)
                 if (m15[i]["close"] - m15[i - 1]["close"] > 0) == (x > 0) and x != 0)
    if nxt15:
        emit("M15 moves >= 1.5 ATR: n=%d" % len(nxt15))
        emit("  next-bar SAME direction: %.0f%%" % (100.0 * same15 / len(nxt15)))
        emit("  next-bar mean %+.3f ATR | %s" % (sum(nxt15) / len(nxt15),
                                                 p5(None, sum(nxt15) / len(nxt15), len(nxt15))))

    emit("")
    emit("(z/t >= 2 ~ 95% confidence; 'SIGNAL' tags mark candidates worth a")
    emit(" dedicated backtest. Directional drifts near 0 are NO-TRADE zones.)")
    with open("C:/FTTest/logs/pattern_scan.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
