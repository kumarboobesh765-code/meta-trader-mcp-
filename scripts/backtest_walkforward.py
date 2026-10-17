r"""Walk-forward decay audit for the deployed FTTest XAUUSD families.

14-day trading windows rolled weekly (7d step) across the last ~90 days of
data. For every window each family is re-run from scratch (signals generated
ONLY from data available at signal time; entries next bar open; pessimistic
same-bar SL) -- so every window is genuinely out-of-sample for the window
before it.

Families = the deployed signal engines, using the EXACT strategy functions
the EAs mirror (imported from forward_test.py) so results are comparable:
  breakout(M15) macross(M30) smc(M15) squeeze(M15) trendpullback(M15)
  donchian(H1) trend(H1) supres(H1) supertrend(H1 5x2.0)
Skipped (engine not reproducible from OHLC here): straddle/london (dual-stop
arming), orderflow (tick buckets), profile (TPO module), aetherflow (own EA),
smvp (user's EA), meanrev (retired 2026-09-30).

Exits: fixed SL vs trailing twin with the DEPLOYED per-family trails
(FTTest twins 0.10/0.3/0.05 since 2026-10-01; supertrend 0.5/0.8/0.20).
Costs: 0.20 spread + $0.04/0.01-lot round trip.

Usage: python backtest_walkforward.py [--weeks 11] [--window 14]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_new_candidates import run, row
from backtest_supertrend import st_dir_pine
import backtest_supertrend as bts
from forward_test import (closed_bars, load_env, atr,
                          strat_breakout, strat_macross, strat_smc,
                          strat_squeeze, strat_trendpullback, strat_trend,
                          strat_supres)

# deployed per-family trails (backtest_trail_full_sweep.py verdicts, 2026-10-01;
# keep in sync with scripts/make_ea_profile.py)
TRAIL_FTTEST = (0.10, 0.3, 0.05)
TRAIL_SUPERTREND = (0.5, 0.8, 0.20)
TRAIL_OF = {"supertrend": TRAIL_SUPERTREND}

FETCH_DAYS = 125
BPD = {"M15": 96, "M30": 48, "H1": 24}
WARM = 320  # bars of warmup before the first window


def sig_events(fn, bars, t0, t1, fixed_levels):
    """Walk the series once; emit events for closed bars with t0<=time<=t1.
    fixed_levels=False -> trust the fn's (sl, tp); True -> standard 2/3 ATR
    (recomputed here so run()'s trail engine gets a consistent 'a')."""
    a_cache = None  # (ATR is per-window now: atr(win) at each signal)
    out = []
    lo = max(WARM, 1)
    for i in range(lo, len(bars)):
        t = bars[i]["time"]
        if t < t0:
            continue
        if t > t1:
            break
        # trendpullback aggregates its own H1 buckets from the M15 series
        # (needs >= 52*96 bars) -- feed it the full prefix; others get a
        # bounded window
        win = bars[0:i + 1] if fn is strat_trendpullback \
            else bars[max(0, i - 300):i + 1]
        r = fn(win)
        if not r or r[0] != "entry":
            continue
        _, side, sl, tp = r
        a = atr(win)   # ATR at signal time -- must match the fn's own SL/TP basis
        if a is None or a <= 0:
            continue
        px = bars[i]["close"]
        if not fixed_levels:
            sl, tp = (px - 2 * a, px + 3 * a) if side == "buy" \
                else (px + 2 * a, px - 3 * a)
        out.append({"sig_i": i, "side": side, "sl": sl, "tp": tp,
                    "entry_px": None, "entry_i": i + 1, "a": a})
    return out


def sig_supertrend_wf(h1, t0, t1, trs):
    out = []
    dir_ = st_dir_pine(h1, 5, 2.0)
    from backtest_aetherflow import sma_atr_at
    for i in range(WARM, len(h1) - 1):
        t = h1[i]["time"]
        if t < t0:
            continue
        if t > t1:
            break
        if dir_[i] == dir_[i - 1]:
            continue
        a = sma_atr_at(trs, i, 14)
        if not a or a <= 0:
            continue
        side = "buy" if dir_[i] == -1 else "sell"
        px = h1[i]["close"]
        sl, tp = (px - 2 * a, px + 3 * a) if side == "buy" else (px + 2 * a, px - 3 * a)
        out.append({"sig_i": i, "side": side, "sl": sl, "tp": tp,
                    "entry_px": None, "entry_i": i + 1, "a": a})
    return out


FAMILIES = [
    # (name, tf, fn, fixed_levels(True=fn's own SL/TP honored))
    ("breakout",      "M15", strat_breakout,      True),
    ("macross",       "M30", strat_macross,       True),
    ("smc",           "M15", strat_smc,           True),
    ("squeeze",       "M15", strat_squeeze,       True),
    ("trendpullback", "M15", strat_trendpullback, True),
    ("donchian",      "H1",  strat_breakout,      True),
    ("trend",         "H1",  strat_trend,         True),
    ("supres",        "H1",  strat_supres,        True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=11, help="windows (1/week)")
    ap.add_argument("--window", type=int, default=14, help="window length (days)")
    ap.add_argument("--json", default=None,
                    help="also dump per-family trail-twin walk-forward stats "
                         "(total/n/PF/pos%%/decay/windows) as JSON")
    args = ap.parse_args()
    global WF_JSON
    WF_JSON = {}

    load_env()
    ok = False
    for attempt in range(5):
        if mt5.initialize():
            ok = True
            break
        print("attach attempt %d failed: %s -- retrying in 10s"
              % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        import time as _t
        _t.sleep(10)
    if not ok:
        print("mt5.initialize() failed after 5 attempts")
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    need = {}
    for name, tf, fn, fl in FAMILIES:
        need[tf] = max(need.get(tf, 0), FETCH_DAYS * BPD[tf] + WARM + 50)
    series = {tf: closed_bars("XAUUSD", tf, n) for tf, n in need.items()}
    h1 = series["H1"]
    trs_h1 = ba.tr_series(h1)
    mt5.shutdown()
    for tf, b in series.items():
        if len(b) < 1000:
            print("not enough %s bars (%d)" % (tf, len(b)))
            return 1

    # deployed trail settings are set per family inside the loop below

    t_last = h1[-1]["time"]
    week = 7 * 86400
    wlen = args.window * 86400
    windows = []  # (t0, t1) oldest first
    for w in range(args.weeks - 1, -1, -1):
        t1 = t_last - w * week
        windows.append((t1 - wlen, t1))

    all_fams = [(n, tf, fn, fl) for n, tf, fn, fl in FAMILIES]
    all_fams.append(("supertrend", "H1", None, True))

    print("XAUUSD walk-forward: %d windows of %dd, rolled weekly | SL 2 / TP 3 ATR "
          "(supres 1.5/2.5, smc 3R) | cost $%.2f/trade | trail per-family "
          "(FTTest 0.10/0.3/0.05, supertrend 0.5/0.8/0.20)"
          % (len(windows), args.window, cost))
    hdr = " ".join("w%-2d" % (len(windows) - i) for i in range(len(windows)))
    print("%-15s %-6s %s   %9s %5s %-5s %5s  %s"
          % ("FAMILY", "TWIN", hdr, "TOTAL", "n", "PF", "pos%", "DECAY(new3-old3)"))

    for name, tf, fn, fl in all_fams:
        bars = series[tf]
        act, dist, step = TRAIL_OF.get(name, TRAIL_FTTEST)
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
        # generate each family's events ONCE over the full series, then slice
        # per window (windows stay OOS: params are static, no re-fitting)
        if name == "supertrend":
            events = sig_supertrend_wf(bars, 0, t_last + 1, trs_h1)
        else:
            events = sig_events(fn, bars, 0, t_last + 1, fl)
        for twin, trailing in (("trail", True), ("fixed", False)):
            nets, n_tr, wins = [], 0, 0
            for t0, t1 in windows:
                ev = [e for e in events if t0 <= bars[e["sig_i"]]["time"] <= t1]
                trades, _ = run(ev, bars, dpu, cost, trailing)
                n, net, pf, w = row(trades)
                nets.append(net)
                n_tr += n
                wins += 1 if net > 0 else 0
            tot = sum(nets)
            pospct = 100.0 * wins / len(windows)
            old3 = sum(nets[:3]) / 3.0
            new3 = sum(nets[-3:]) / 3.0
            decay = new3 - old3
            tag = ""
            if tot < 0 and new3 < 0:
                tag = " <- BLEEDING"
            elif decay < -60 and tot > 0:
                tag = " <- DECAYING"
            print("%-15s %-6s %s   %+9.2f %5d %-5s %4.0f%%  %+8.2f%s"
                  % (name, twin,
                     " ".join("%+5.0f" % x for x in nets),
                     tot, n_tr,
                     (pf if isinstance(pf, str) else "%.2f" % pf),
                     pospct, decay, tag))
            if twin == "trail":
                # machine-readable dump for the dashboard scorecard
                # (11x14d windows, per-family deployed trail; PF inf-safe)
                WF_JSON.setdefault(name, {
                    "total": round(tot, 2), "n": n_tr, "pf": None if pf == "inf"
                    else (pf if isinstance(pf, str) else round(pf, 2)),
                    "pos_pct": round(pospct), "decay": round(decay, 2),
                    "windows": [round(x, 2) for x in nets]})
        print()
    if args.json:
        import json as _json
        with open(args.json, "w", encoding="utf-8") as fh:
            _json.dump(WF_JSON, fh, indent=1)
        print("wf json -> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
