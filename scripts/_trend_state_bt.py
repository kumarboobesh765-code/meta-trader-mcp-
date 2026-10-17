"""Ad-hoc: state-machine-faithful backtest of strat_trend (live parity).

The walk-forward engine (backtest_new_candidates.run) differs from the live
EA state machine in two ways that matter in choppy regimes:
  1. busy-lock: after an intrabar exit at bar X it SKIPS the signal emitted at
     X's close -- the live EA takes it at X+1's open (verified vs journal:
     live re-entries at :00 server right after trail/SL stops).
  2. no reversal modeling: the live EA closes and reverses when the signal
     flips; the bt engine holds to SL/TP.

This script reimplements the EA's actual loop (one position; at each bar open
act on the previous closed bar's signal: reverse if opposed, enter if flat and
aligned; then manage SL/TP/trail intrabar with live-parity rolling ATR) and
runs it over (A) the exact live window and (B) the 11x14d walk-forward.

Verdict input: if the state-machine walk-forward is still strongly positive,
the family keeps (bad regime); if it collapses, the edge was an engine
artifact and the family retires.

Runs ON THE VPS (MT5 attach). Read-only.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from backtest_walkforward import sig_events, TRAIL_FTTEST, FETCH_DAYS, BPD, WARM
from forward_test import closed_bars, load_env, strat_trend


def atr_series14(bars):
    n = len(bars)
    trs = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    out = [None] * n
    for i in range(14, n):
        out[i] = sum(trs[i - 13:i + 1]) / 14.0
    return out


def run_state(events, bars, dpu, cost, trailing, atr_at):
    """Live-parity state machine. Returns list of trade pnl."""
    sig = {ev["sig_i"]: ev for ev in events}
    act, dist, step = ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP
    pos = None
    trades = []
    for i in range(WARM + 1, len(bars)):
        s = sig.get(i - 1)
        # --- act on the just-closed bar's signal at this bar's open ---
        if s is not None:
            if pos is not None and s["side"] != pos["side"]:
                o = bars[i]["open"]
                raw = (o - pos["entry"]) if pos["side"] == "buy" \
                    else (pos["entry"] - o)
                trades.append(raw * dpu - cost)
                pos = None
            if pos is None:
                pos = {"side": s["side"], "entry": bars[i]["open"],
                       "sl": s["sl"], "tp": s["tp"], "a": s["a"],
                       "best": None}
        if pos is None:
            continue
        # --- intrabar management during bar i ---
        b = bars[i]
        if pos["side"] == "buy":
            if b["low"] <= pos["sl"]:
                trades.append((pos["sl"] - pos["entry"]) * dpu - cost)
                pos = None
                continue
            if trailing:
                a = atr_at[i - 1] or pos["a"]
                if b["high"] - pos["entry"] >= act * a:
                    pos["best"] = max(pos["best"] or b["high"], b["high"])
                    new_sl = pos["best"] - dist * a
                    if new_sl > pos["sl"] + step * a:
                        pos["sl"] = new_sl
            if b["high"] >= pos["tp"]:
                trades.append((pos["tp"] - pos["entry"]) * dpu - cost)
                pos = None
        else:
            if b["high"] >= pos["sl"]:
                trades.append((pos["entry"] - pos["sl"]) * dpu - cost)
                pos = None
                continue
            if trailing:
                a = atr_at[i - 1] or pos["a"]
                if pos["entry"] - b["low"] >= act * a:
                    pos["best"] = min(pos["best"] or b["low"], b["low"])
                    new_sl = pos["best"] + dist * a
                    if new_sl < pos["sl"] - step * a:
                        pos["sl"] = new_sl
            if b["low"] <= pos["tp"]:
                trades.append((pos["entry"] - pos["tp"]) * dpu - cost)
                pos = None
    if pos is not None:
        o = bars[-1]["close"]
        raw = (o - pos["entry"]) if pos["side"] == "buy" \
            else (pos["entry"] - o)
        trades.append(raw * dpu - cost)
    return trades


def stats(ts):
    if not ts:
        return "n=0"
    wins = [t for t in ts if t > 0]
    loss = [t for t in ts if t <= 0]
    gw, gl = sum(wins), abs(sum(loss))
    pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
    return "n=%d net=%+.2f win=%.0f%% PF=%s avg=%+.2f" % (
        len(ts), sum(ts), 100.0 * len(wins) / len(ts), pf,
        sum(ts) / len(ts))


def main():
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
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
    atr_at = atr_series14(bars)
    ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = TRAIL_FTTEST

    events = sig_events(strat_trend, bars, 0, bars[-1]["time"] + 1, True)
    print("bars=%d events=%d cost=$%.2f" % (len(bars), len(events), cost))

    t0 = datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp()
    ev_live = [e for e in events if bars[e["sig_i"]]["time"] >= t0]
    print("\n=== A) exact live window (live actuals: trail n=27 -146.06 | "
          "fixed n=9 -216.58) ===")
    for label, trailing in (("state trail", True), ("state fixed", False)):
        ts = run_state(ev_live, bars, dpu, cost, trailing, atr_at)
        print("  %-12s %s" % (label, stats(ts)))

    print("\n=== B) walk-forward 11x14d, state machine ===")
    t_last = bars[-1]["time"]
    week, wlen = 7 * 86400, 14 * 86400
    wins = [(t_last - w * week - wlen, t_last - w * week)
            for w in range(10, -1, -1)]
    hdr = " ".join("w%-2d" % (11 - i) for i in range(11))
    print("%-12s %s   %9s %5s" % ("VARIANT", hdr, "TOTAL", "n"))
    for label, trailing in (("state trail", True), ("state fixed", False),
                            ("bt trail(ref)", None)):
        nets, nn = [], 0
        for (a, b) in wins:
            ev = [e for e in events
                  if a <= bars[e["sig_i"]]["time"] <= b]
            if trailing is None:
                # reference: original walk-forward engine (busy-lock, no
                # reversals), frozen ATR -- via backtest_new_candidates.run
                from backtest_new_candidates import run
                ts, _ = run(ev, bars, dpu, cost, True)
            else:
                ts = run_state(ev, bars, dpu, cost, trailing, atr_at)
            nets.append(sum(ts))
            nn += len(ts)
        print("%-12s %s   %+9.2f %5d"
              % (label, " ".join("%+5.0f" % x for x in nets), sum(nets), nn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
