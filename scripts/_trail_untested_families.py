"""Trail probe for the FOUR families the tightening sweep never covered.

_trail_tighter_sweep.py only measured breakout/macross/smc/squeeze/trend (the
forward_test.strat_* families). Four deployed trail twins were left at the old
0.10/0.3/0.05 with no evidence:

  donchian       (chart28, H1,  magic 940011)  -> backtest_new_candidates.sig_donchian
  trendpullback  (chart26, M15, magic 940010)  -> sig_trendpullback  [RETIRED slot]
  fixfade        (chart24, M15, magic 940009)  -> backtest_institutional.fix_fade_events
  vwaprev        (chart32, M15, magic 940013)  -> backtest_institutional.vwap_rev_events

fixfade/vwaprev exit on a TIME STOP (max_bars) rather than SL/TP alone, so they
need a trail-capable walker -- walk_timed() in backtest_institutional cannot
trail. run_events_trail below is that walker: same pessimistic SL-before-TP
ordering and same time stop, with the ATR ratchet layered on top, so the only
difference between arms is the trail itself.

Each family also gets a WINDOW split (5 sequential non-overlapping slices of the
same data) so a pooled win cannot hide a single-regime result -- the same test
that caught the pooled-only risk in _trail_tighter_windows.py.

Read-only. Runs ON THE VPS. Writes C:/FTTest/logs/trail_untested.txt
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as bae
import backtest_institutional as bi
import backtest_new_candidates as bnc
import backtest_trailing_check as btc
from backtest_new_candidates import (market_events, run as bnc_run,
                                     sig_donchian, sig_trendpullback,
                                     h1_index_map)
from backtest_aetherflow import tr_series
from backtest_institutional import (fetch_vol_bars, fix_fade_events,
                                    vwap_rev_events)
from forward_test import closed_bars, load_env

# patched bae.TRAIL_* must reach every harness that trails
bnc.walk_exit_trail = bae.walk_exit_trail

OUT = []
NWIN = 5
OUTPATH = r"C:\FTTest\logs\trail_untested.txt"

CANDS = [
    (0.10, 0.3, 0.05, "DEPLOYED 0.10/0.3/0.05"),
    (0.06, 0.20, 0.03, "tight    0.06/0.20/0.03"),
    (0.05, 0.15, 0.02, "tightest 0.05/0.15/0.02"),
    (0.04, 0.12, 0.02, "scalp    0.04/0.12/0.02"),
]

COST = bi.COST


def emit(s=""):
    print(s, flush=True)
    OUT.append(s)
    try:
        with open(OUTPATH, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass


def patch(act, dist, step):
    bae.TRAIL_ACTIVATE, bae.TRAIL_DIST, bae.TRAIL_STEP = act, dist, step
    btc.TRAIL_ACTIVATE, btc.TRAIL_DIST, btc.TRAIL_STEP = act, dist, step


# ------------------------------------------------- trail walker (time-stopped)
def walk_timed_trail(side, entry, sl, tp, a, bars, start_i, max_bars):
    """walk_timed() + an ATR ratchet. SL is checked BEFORE the ratchet on each
    bar (pessimistic: a bar that reaches both levels books the SL), and the
    time stop still applies last."""
    cur_sl = sl
    best = None
    last = min(len(bars) - 1, start_i + max_bars - 1)
    for j in range(start_i, last + 1):
        b = bars[j]
        if side == "buy":
            if b["low"] <= cur_sl:
                return cur_sl, j
            if b["high"] - entry >= bae.TRAIL_ACTIVATE * a:
                best = max(best, b["high"]) if best else b["high"]
                new_sl = best - bae.TRAIL_DIST * a
                if new_sl > cur_sl + bae.TRAIL_STEP * a:
                    cur_sl = new_sl
            if b["high"] >= tp:
                return tp, j
        else:
            if b["high"] >= cur_sl:
                return cur_sl, j
            if entry - b["low"] >= bae.TRAIL_ACTIVATE * a:
                best = min(best, b["low"]) if best else b["low"]
                new_sl = best + bae.TRAIL_DIST * a
                if cur_sl == 0 or new_sl < cur_sl - bae.TRAIL_STEP * a:
                    cur_sl = new_sl
            if b["low"] <= tp:
                return tp, j
    return bars[last]["close"], last


def run_events_trail(events, bars, dpu, trailing, cost):
    """bi.run_events clone with an optional ATR trail and an explicit cost
    deduction (bi's original passes dpu=1.0 and never charges COST)."""
    out = []
    busy_until = -1
    for sig_i, side, sl, tp, maxb in events:
        if sig_i <= busy_until:
            continue
        if sig_i + 1 >= len(bars):
            break
        nxt = bars[sig_i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            out.append(((sl - entry) if side == "buy"
                        else (entry - sl)) * dpu - cost)
            busy_until = sig_i + 1
            continue
        # the event carries no ATR; recover it from the 3-ATR risk geometry
        risk = abs(tp - sl) / 3.0
        if trailing and risk > 0:
            px, ex_i = walk_timed_trail(side, entry, sl, tp, risk, bars,
                                        sig_i + 2, maxb)
        else:
            px, ex_i = bi.walk_timed(side, sl, tp, bars, sig_i + 2, maxb)
        raw = (px - entry) if side == "buy" else (entry - px)
        out.append(raw * dpu - cost)
        busy_until = ex_i
    return out


# --------------------------------------------------------------- window logic
def windowed(name, net_fn, bars, configs, tag="bars"):
    """net_fn(triple, lo, hi) -> net over the bar-index range [lo, hi).
    Builds nothing per config; each config is scored on identical windows."""
    n = len(bars)
    cut = n // NWIN
    bounds = [(w * cut, (w + 1) * cut if w < NWIN - 1 else n)
              for w in range(NWIN)]
    all_nets, pooled, pooled_n = [], [], []
    for act, dist, step, tagname in configs:
        patch(act, dist, step)
        nets, ns = [], []
        for lo, hi in bounds:
            seg = bars[lo:hi]
            v, k = net_fn(seg, lo, hi)
            nets.append(v)
            ns.append(k)
        all_nets.append(nets)
        pooled.append(sum(nets))
        pooled_n.append(sum(ns))
    dep = pooled[0]
    emit("\n== %s : %d %s, %d windows ==" % (name, n, tag, NWIN))
    emit("   %-26s" % "config"
         + "".join("  W%-7d" % (w + 1) for w in range(NWIN))
         + "     TOTAL      n")
    for ci, (_a, _d, _s, tagname) in enumerate(configs):
        emit("   %-26s" % tagname
             + "".join("%9.0f" % v for v in all_nets[ci])
             + "%10.0f %5d" % (pooled[ci], pooled_n[ci]))
    for ci in range(1, len(configs)):
        won = sum(1 for w in range(NWIN)
                  if all_nets[ci][w] > all_nets[0][w] + 1e-9)
        loo = [sum(all_nets[ci][:w]) + sum(all_nets[ci][w + 1:])
               for w in range(NWIN)]
        verdict = ("ROBUST" if won >= NWIN - 1 and min(loo) > min(
            [sum(all_nets[0][:w]) + sum(all_nets[0][w + 1:])
             for w in range(NWIN)]) else
                   ("MIXED" if won >= NWIN // 2 else "WEAK"))
        emit("   -> %-26s beats deployed %d/%d windows | pooled %+.0f (%+.0f)"
             " | worst LOO %+.0f [%s]"
             % (configs[ci][3], won, NWIN, pooled[ci], pooled[ci] - dep,
                min(loo), verdict))
        emit("      per-window: %s"
             % " ".join("W%d:%s" % (w + 1,
                                    "+" if all_nets[ci][w] > all_nets[0][w]
                                    + 1e-9 else "-") for w in range(NWIN)))
    return pooled, pooled_n


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
        emit("mt5.initialize failed after 5 attempts")
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        emit("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04
    emit("TRAIL PROBE -- UNTESTED FAMILIES -- %s demo | cost $%.2f/trade"
         % (acc.login, cost))
    emit("donchian / trendpullback / fixfade / vwaprev, pooled + %d windows"
         % NWIN)

    bars15 = fetch_vol_bars("M15", 100 * 96 + 320)
    h1 = closed_bars("XAUUSD", "H1", 100 * 24 + 320)
    if len(bars15) < 4000 or len(h1) < 1000:
        emit("not enough bars: m15=%d h1=%d" % (len(bars15), len(h1)))
        mt5.shutdown()
        return 1
    trs15, trs1 = tr_series(bars15), tr_series(h1)
    hmap = h1_index_map(bars15, h1)
    t0 = 0

    # ---- donchian (H1 host, market_events + bnc_run) ----
    emit("\n########## donchian (H1) ##########")
    ev_don = market_events(sig_donchian(h1, trs1, t0), h1)

    def don_fn(seg, lo, hi):
        # re-index events onto the slice so indices stay valid for bnc_run
        sub = [e for e in ev_don if lo <= e["sig_i"] < hi]
        if not sub:
            return 0.0, 0
        off = lo
        reb = [dict(e, sig_i=e["sig_i"] - off) for e in sub]
        tr, _ = bnc_run(reb, seg, dpu, cost, True)
        tr = tr or []
        return sum(tr), len(tr)

    windowed("donchian pooled-vs-windows", don_fn, h1, CANDS, "H1 bars")

    # ---- trendpullback (M15 host, needs H1 context) ----
    emit("\n########## trendpullback (M15) ##########")
    sig_tp = sig_trendpullback(bars15, h1, hmap, trs15, trs1, t0)
    ev_tp = market_events(sig_tp, bars15)

    def tp_fn(seg, lo, hi):
        sub = [e for e in ev_tp if lo <= e["sig_i"] < hi]
        if not sub:
            return 0.0, 0
        reb = [dict(e, sig_i=e["sig_i"] - lo) for e in sub]
        tr, _ = bnc_run(reb, seg, dpu, cost, True)
        tr = tr or []
        return sum(tr), len(tr)

    windowed("trendpullback pooled-vs-windows", tp_fn, bars15, CANDS, "M15 bars")

    # ---- fixfade / vwaprev (M15, time-stopped, own trail walker) ----
    atr15 = {i: bae.sma_atr_at(trs15, i) for i in range(len(bars15))}
    for nm, fn in (("fixfade", fix_fade_events),
                   ("vwaprev", vwap_rev_events)):
        emit("\n########## %s (M15) ##########" % nm)
        evs = fn(bars15, t0, atr15)
        times = [b["time"] for b in bars15]

        def inst_fn(seg, lo, hi):
            t_lo, t_hi = times[lo], times[hi - 1]
            sub = [e for e in evs if lo <= e[0] < hi]
            if not sub:
                return 0.0, 0
            tr = run_events_trail(sub, seg, dpu, True, cost)
            return sum(tr), len(tr)

        windowed("%s pooled-vs-windows" % nm, inst_fn, bars15, CANDS, "M15 bars")

    mt5.shutdown()
    emit("\n-> C:/FTTest/logs/trail_untested.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())