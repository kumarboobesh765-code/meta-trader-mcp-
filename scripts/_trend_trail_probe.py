"""Ad-hoc probe: does the live rolling-ATR trail explain trend-T's divergence?

The live core recomputes g_atr at EVERY closed bar (OnTick) and the trail
distances use that rolling value; the walk-forward trail engine froze the
entry-time ATR. This probe runs strat_trend over:
  (A) the exact live window (since 2026-09-29)
  (B) the 11x14d walk-forward windows
comparing three exits:
  fixed          -> static SL/TP (walk-forward engine, unchanged)
  trail_frozen   -> walk-forward trail engine as-is (entry ATR frozen)
  trail_rolling  -> live-parity: per-bar ATR14 recompute (g_atr at bar close,
                    used for the next bar's trail distances/step/activation)

Live reference (deals.csv, both twins, 2026-09-29 -> 10-02):
  trail twin n=27 net=-146.06 | fixed twin n=9 net=-216.58

Runs ON THE VPS (MT5 attach). Read-only.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_new_candidates import run, row
from backtest_walkforward import sig_events, TRAIL_FTTEST, FETCH_DAYS, BPD, WARM
from forward_test import closed_bars, load_env, strat_trend


def atr_series14(bars):
    """ATR14 at each bar (mean of last 14 TRs ending at that bar), like
    forward_test.atr(bars, 14) evaluated on the window ending at the bar."""
    n = len(bars)
    trs = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    out = [None] * n
    for i in range(14, n):
        out[i] = sum(trs[i - 13:i + 1]) / 14.0
    return out


def walk_exit_trail_roll(side, entry, sl, tp, a0, bars, start_i, atr_at):
    """walk_exit_trail with live-parity rolling ATR: while bar j forms, the
    EA's g_atr = ATR14 at close of bar j-1 (recomputed every closed bar)."""
    cur_sl = sl
    best = None
    mods = 0
    act, dist, step = ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP
    for j in range(start_i, len(bars)):
        b = bars[j]
        a = atr_at[j - 1] if (j >= 1 and atr_at[j - 1]) else a0
        if side == "buy" and b["low"] <= cur_sl:
            return cur_sl, j, mods
        if side == "sell" and b["high"] >= cur_sl:
            return cur_sl, j, mods
        if side == "buy":
            if b["high"] - entry >= act * a:
                best = max(best, b["high"]) if best else b["high"]
                new_sl = best - dist * a
                if new_sl > cur_sl + step * a:
                    cur_sl = new_sl
                    mods += 1
            if b["high"] >= tp:
                return tp, j, mods
        else:
            if entry - b["low"] >= act * a:
                best = min(best, b["low"]) if best else b["low"]
                new_sl = best + dist * a
                if cur_sl == 0 or new_sl < cur_sl - step * a:
                    cur_sl = new_sl
                    mods += 1
            if b["low"] <= tp:
                return tp, j, mods
    return bars[-1]["close"], len(bars) - 1, mods


def run_roll(events, bars, dpu, cost, atr_at):
    trades, mods = [], 0
    busy = -1
    for ev in events:
        if ev["sig_i"] <= busy:
            continue
        side, sl, tp, a = ev["side"], ev["sl"], ev["tp"], ev["a"]
        i = ev["sig_i"]
        if i + 1 >= len(bars):
            break
        entry = bars[i + 1]["open"]
        if (side == "buy" and bars[i + 1]["low"] <= sl) or \
           (side == "sell" and bars[i + 1]["high"] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            trades.append({"pnl": raw * dpu - cost, "ex_i": i + 1})
            busy = i + 1
            continue
        px, ex_i, m = walk_exit_trail_roll(side, entry, sl, tp, a, bars,
                                           i + 2, atr_at)
        mods += m
        raw = (px - entry) if side == "buy" else (entry - px)
        trades.append({"pnl": raw * dpu - cost, "ex_i": ex_i})
        busy = ex_i
    return trades, mods


def fmt_trips(ts, bars):
    return " ".join("%s%+.0f" % (
        datetime.fromtimestamp(bars[t["ex_i"]]["time"], tz=timezone.utc)
        .strftime("%d/%H:%M "), t["pnl"]) for t in ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-29")
    ap.add_argument("--windows", type=int, default=11)
    ap.add_argument("--window", type=int, default=14)
    args = ap.parse_args()

    load_env()
    print("P: env loaded", flush=True)
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),), flush=True)
        return 1
    print("P: mt5 attached", flush=True)
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04
    bars = closed_bars("XAUUSD", "H1", FETCH_DAYS * BPD["H1"] + WARM + 50)
    mt5.shutdown()
    print("P: bars=%d" % len(bars), flush=True)
    atr_at = atr_series14(bars)

    t0 = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp()
    t1 = bars[-1]["time"] + 1
    events = sig_events(strat_trend, bars, 0, t1, True)
    ev_live = [e for e in events
               if bars[e["sig_i"]]["time"] >= t0]
    print("P: events=%d (live=%d)" % (len(events), len(ev_live)), flush=True)
    print("=== A) exact live window %s -> %s (events=%d) ==="
          % (args.since,
             datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc)
             .strftime("%m-%d %H:%M"), len(ev_live)))
    print("live reference: trail n=27 net=-146.06 | fixed n=9 net=-216.58")

    ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = TRAIL_FTTEST

    tr_f, _ = run(ev_live, bars, dpu, cost, True)
    n, net, pf, w = row(tr_f)
    print("\ntrail_frozen  n=%d net=%+.2f win=%s%% PF=%s" % (n, net, w, pf))
    print("  pnls: " + " ".join("%+.0f" % x for x in tr_f))

    tr_r, mods = run_roll(ev_live, bars, dpu, cost, atr_at)
    n, net, pf, w = row([t["pnl"] for t in tr_r])
    print("\ntrail_rolling n=%d net=%+.2f win=%s%% PF=%s trail_mods=%d"
          % (n, net, w, pf, mods))
    print("  trips: " + fmt_trips(tr_r, bars))

    tr_x, _ = run(ev_live, bars, dpu, cost, False)
    n, net, pf, w = row(tr_x)
    print("\nfixed         n=%d net=%+.2f win=%s%% PF=%s" % (n, net, w, pf))

    print("\n=== B) walk-forward %dx%dd windows (trend only) ==="
          % (args.windows, args.window))
    t_last = bars[-1]["time"]
    week, wlen = 7 * 86400, args.window * 86400
    wins = [(t_last - w * week - wlen, t_last - w * week)
            for w in range(args.windows - 1, -1, -1)]
    hdr = " ".join("w%-2d" % (args.windows - i) for i in range(args.windows))
    print("%-14s %s   %9s %5s" % ("VARIANT", hdr, "TOTAL", "n"))
    for label, roll in (("trail_frozen", False), ("trail_rolling", True)):
        nets, nn = [], 0
        for (a, b) in wins:
            ev = [e for e in events
                  if a <= bars[e["sig_i"]]["time"] <= b]
            if roll:
                ts, _ = run_roll(ev, bars, dpu, cost, atr_at)
                ts = [t["pnl"] for t in ts]
            else:
                ts, _ = run(ev, bars, dpu, cost, True)
            nets.append(sum(ts))
            nn += len(ts)
        print("%-14s %s   %+9.2f %5d"
              % (label, " ".join("%+5.0f" % x for x in nets),
                 sum(nets), nn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
