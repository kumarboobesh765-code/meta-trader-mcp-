"""Institutional v2: three gaps in the v1 campaign (backtest_institutional.py).

1. sweep_abs never got a TRAIL arm -- v1's run_events() is fixed-only with a
   time stop. Every rig result says trail beats fixed, so the sweep verdict
   is incomplete without it.
2. vwap_rev has no regime gate -- it fades every 1.5-sigma touch including
   trend days, where fading VWAP is suicide. v2 tests range-days-only
   (signal-day H1 ATR below its trailing 20-day median).
3. News drift was never built (needs a calendar). v2 hardcodes an
   APPROXIMATE 2026 high-impact calendar below -- NFP by first-Friday rule,
   CPI/FOMC as fixed dates. Times are UTC release stamps; the signal reads
   30 min after the stamp. Treat the drift verdict as directional, not
   precise: a wrong stamp by an hour moves entries, it does not invent drift.

CORRECTNESS NOTE: v1's run_events() appends raw*dpu with NO cost subtracted,
even though the header claims $0.24/trade. Every v1 verdict is inflated by
$0.24 x n. This script scores everything cost-aware (COST deducted per trip)
and does NOT touch run_events(), so v1 numbers stay comparable as published.

Usage (ON THE VPS -- needs MetaTrader5 + terminal data):
  python C:\\FTTest\\scripts\\backtest_institutional_v2.py [--days 200]
"""
import argparse
import calendar as _cal
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
import backtest_institutional as v1
from backtest_new_candidates import row

COST = 0.24          # $/0.01-lot RT, deducted per trip (v1 forgot this)
DPU = 1.0
TIGHT = (0.05, 0.15, 0.02)   # deployed triple under test
BPD_H1 = 24

# ----------------- approximate 2026 high-impact calendar (WALL stamps) ------
# NFP: first Friday of month, 12:30. CPI ~mid-month 12:30. FOMC ~18:00 day two.
#
# WALL-clock construction (deliberate): MT5 bar epochs may be true-UTC or
# server-wall-as-epoch (Vantage is UTC+3; the repo reads deal times as broker
# wall). A true-UTC stamp matched against inflated bar times lands ~3h early
# -- every read pre-release, zero real events. Both sides here use naive wall
# clock (bar wall = utcfromtimestamp, stamp wall = calendar wall re-encoded),
# so whichever frame the data lives in, si lands on the release bar. EST
# Nov-Mar shifts the real print to 13:30 wall; folded into the +30min read
# delay (documented, not silent).
_NFP = []
for _m in range(1, 13):
    for _d in range(1, 8):
        import datetime as _dt
        if _dt.date(2026, _m, _d).weekday() == 4:
            _NFP.append(_dt.date(2026, _m, _d).isoformat())
            break
_CPI = ["2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-12",
        "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14",
        "2026-11-10", "2026-12-10"]
_FOMC = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
         "2026-09-16", "2026-10-28", "2026-12-09"]
NEWS_DAYS = {}   # 'YYYY-MM-DD' -> release WALL stamp (see above)
for _d in _NFP + _CPI:
    NEWS_DAYS[_d] = _cal.timegm(
        datetime(2026, int(_d[5:7]), int(_d[8:10]), 12, 30).timetuple())
for _d in _FOMC:
    NEWS_DAYS[_d] = _cal.timegm(
        datetime(2026, int(_d[5:7]), int(_d[8:10]), 18, 0).timetuple())


# ------------------------------------------------------------------ runners
def run_cost(events, bars, trailing=None, cap=None):
    """v1 run_events semantics + COST per trip + optional trail + cap.

    events: (sig_i, side, sl, tp, maxb). trail: None (fixed) or (act,dist,step)
    which sets bae globals exactly like backtest_swing.set_trail. cap: max
    bars to hold (None = event's own maxb).
    """
    if trailing:
        bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = trailing
    out, busy = [], -1
    for sig_i, side, sl, tp, maxb in events:
        if sig_i <= busy:
            continue
        if sig_i + 1 >= len(bars):
            break
        nxt = bars[sig_i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            out.append(((sl - entry) if side == "buy" else (entry - sl))
                       * DPU - COST)
            busy = sig_i + 1
            continue
        hold = maxb if cap is None else min(maxb, cap)
        if trailing:
            a = abs(entry - sl) / 1.5   # both engines use 1.5 ATR stops
            view = bars[:sig_i + 2 + hold]
            px, ex_i, _m = bae.walk_exit_trail(side, entry, sl, tp, a, view,
                                               sig_i + 2)
        else:
            px, ex_i = v1.walk_timed(side, sl, tp, bars, sig_i + 2, hold)
        out.append(((px - entry) if side == "buy" else (entry - px))
                   * DPU - COST)
        busy = ex_i
    return out


def score(trades):
    n, net, pf, win = row(trades)
    return "%5d %+10.2f %6.1f%% %8s %+9.2f" % (n, net, win, pf,
                                              (net / n) if n else 0.0)


# ------------------------------------------------------------- news engine
EXP_ATR = 2.0    # post-stamp 45-min range must clear this many ATRs
GAP_SKIP = 7200  # skip stamp if first bar at/after it is this far out


def news_drift_events(bars15, atrs):
    """30 min post-stamp: the 45-min POST-stamp range must clear EXP_ATR
    (ATR-normalized, no warmup, no median poisoning). Two earlier designs
    both vetoed everything: gating on the PRE-stamp window (uniformly tight
    before a print), then gating on 2x the trailing median of post ranges
    (the median gets inflated by the very expansions it should detect, and
    the 5-stamp warmup consumed the two best events in the window).
    Direction = si+2 close vs pre-stamp price. SL = pre-stamp price (drift
    failed if revisited), TP = 2.5 ATR, flat same wall day. Stamps landing
    on a closed market (e.g. NFP on Good Friday 2026-04-03, next bar = Sun
    open gap) are skipped via GAP_SKIP."""
    ev = []
    for day, stamp in sorted(NEWS_DAYS.items()):
        if stamp > bars15[-1]["time"] or stamp < bars15[320]["time"]:
            continue
        si = next((i for i, b in enumerate(bars15) if b["time"] >= stamp),
                  None)
        if si is None or si < 60 or si + 4 >= len(bars15):
            continue
        if bars15[si]["time"] - stamp > GAP_SKIP:
            continue               # closed market, si is a gap bar
        a = atrs[si]
        if not a:
            continue
        pre = bars15[si]["open"]   # ~stamp price
        post = max(b["high"] for b in bars15[si:si + 3]) - \
            min(b["low"] for b in bars15[si:si + 3])
        if post < EXP_ATR * a:
            continue               # no expansion, no trade
        rd = bars15[si + 2]        # ~30 min post stamp
        if rd["close"] > pre and rd["close"] > rd["open"]:
            ev.append((si + 2, "buy", pre, rd["close"] + 2.5 * a, 32))
        elif rd["close"] < pre and rd["close"] < rd["open"]:
            ev.append((si + 2, "sell", pre, rd["close"] - 2.5 * a, 32))
    return ev


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=200)
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit("initialize failed: %r" % mt5.last_error())

    bars15 = v1.fetch_vol_bars("M15", args.days * 96 + 320)
    h1r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 1,
                                  args.days * 24 + 320)
    mt5.shutdown()
    bars_h1 = [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"]} for r in h1r]
    print("M15=%d H1=%d window=%dd" % (len(bars15), len(bars_h1), args.days))

    trs15 = bae.tr_series(bars15)
    atr15 = {i: bae.sma_atr_at(trs15, i) for i in range(len(bars15))}
    trs_h1 = bae.tr_series(bars_h1)
    atr_h1 = [bae.sma_atr_at(trs_h1, i) for i in range(len(bars_h1))]
    h1_idx = {b["time"]: i for i, b in enumerate(bars_h1)}

    # H1-ATR trailing-20d median lookup per M15 bar (causal: last CLOSED H1)
    def range_day(sig_time):
        j = next((i for i in range(len(bars_h1) - 1, -1, -1)
                  if bars_h1[i]["time"] + 3600 <= sig_time), None)
        if j is None or j < 480 or not atr_h1[j]:
            return None
        win = [x for x in atr_h1[j - 480:j] if x]
        if len(win) < 100:
            return None
        s = sorted(win)
        return atr_h1[j] < s[len(s) // 2]

    print("\n%-28s %5s %10s %7s %8s %9s" % ("arm", "n", "net", "win%",
                                           "PF", "per-trip"))
    # 1. sweep fixed vs trail
    sw = v1.sweep_abs_events(bars15, 0, atr15)
    print("%-28s %s" % ("sweep fixed 1.5/3.0",
                        score(run_cost(sw, bars15))))
    print("%-28s %s" % ("sweep trail tight",
                        score(run_cost(sw, bars15, TIGHT))))
    # 2. vwap plain vs range-gated
    vw = v1.vwap_rev_events(bars15, 0, atr15)
    print("%-28s %s" % ("vwap plain", score(run_cost(vw, bars15))))
    # diagnostic: is the gate broken, or is the whole window high-vol?
    _probe = [range_day(b["time"]) for b in bars15[::96]]
    _known = [x for x in _probe if x is not None]
    print("range-day share of sampled bars: %.0f%% (%d/%d known)" % (
        100 * sum(1 for x in _known if x) / max(1, len(_known)),
        sum(1 for x in _known if x), len(_known)))
    gated, unk = [e for e in vw
                  if range_day(bars15[e[0]]["time"]) is True], \
                 [e for e in vw
                  if range_day(bars15[e[0]]["time"]) is None]
    print("%-28s %s   (of %d, %d regime-unknown skipped)"
          % ("vwap range-days only", score(run_cost(gated, bars15)),
             len(vw), len(unk)))
    # 3. news drift fixed vs trail
    nd = news_drift_events(bars15, atr15)
    print("%-28s %s" % ("news-drift fixed 2.5ATR",
                        score(run_cost(nd, bars15))))
    print("%-28s %s" % ("news-drift trail tight",
                        score(run_cost(nd, bars15, TIGHT))))
    print("\nnews events: %d  (calendar is approximate -- see header)" % len(nd))


if __name__ == "__main__":
    sys.exit(main())
