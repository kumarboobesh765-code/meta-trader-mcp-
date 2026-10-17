"""Why is aetherflow-M30 negative in EVERY trail config?

Facts so far:
  * 100d probe (scripts/_trail_tighter_sweep.py): fixed/trail both lose.
    deployed 0.2/0.5/0.10 = -$305, tightening to 0.08/0.25/0.04 = -$131.
    Tightening helps but does NOT flip it positive -> the problem is the
    SIGN/STRUCTURE of the edge, not the exit.
  * The H4 leg was fixed exactly this way: uncapped holds were the bleed
    (60d fixed -$408 uncapped vs +$97 capped at 12 bars; trail +$411 capped).
    The M30 legs were explicitly LEFT UNCAPPED ("they exit fast and score
    better that way") -- that assumption is what this probe tests.
  * The trail config sweep used the H4 FEED to grade the M30 leg
    ("aetherflow-M30 (UT, H4 feed as deployed)"). That is a possible
    harness/feed mismatch worth confirming: the LIVE M30 twins (950002 /
    960002, charts 19/20) run on PERIOD_M30.

So this probe, for the M30 leg specifically:
  1) runs BOTH feeds (true M30 bars, and the H4 bars the sweep used) so a
     feed mismatch shows up as a sign difference rather than hiding;
  2) prints PER-TRADE detail (side, hold bars, exit reason, pnl) so the
     losing shape is visible instead of inferred;
  3) sweeps TIME CAPS in bars (the lever that rescued H4) for fixed and
     trail, so "should M30 be capped too?" is answered by evidence;
  4) reports hold-time distribution vs pnl -- the H4 bleed was long holds.

Read-only. Runs ON THE VPS. Writes C:/FTTest/logs/aetherflow_m30.txt
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from forward_test import closed_bars, load_env

OUT = []
OUTPATH = r"C:\FTTest\logs\aetherflow_m30.txt"
CAPS = (0, 4, 6, 8, 10, 12, 16, 20)
TRAILS = [
    (0.2, 0.5, 0.10, "deployed 0.2/0.5/0.10"),
    (0.08, 0.25, 0.04, "tightest 0.08/0.25/0.04"),
]


def emit(s=""):
    print(s, flush=True)
    OUT.append(s)
    try:
        with open(OUTPATH, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass


def run_detail(eng, bars, dpu, cost, mode, trailing, cap):
    """run_backtest clone that also records per-trade detail.

    Mirrors ba.run_backtest EXACTLY (same warmup, same same-bar pessimistic
    SL, same busy lock) and only adds the optional bar cap + a detail row, so
    cap=0/trailing=False reproduces the shipped numbers as a control."""
    rows = []
    busy_until = -1
    for i in range(ba.WARMUP, eng.n - 2):
        if i <= busy_until:
            continue
        want_buy, want_sell = eng.ut_buy[i], eng.ut_sell[i]
        if not want_buy or want_sell:
            continue
        side = "buy" if want_buy else "sell"
        a = ba.sma_atr_at(eng.trs, i)
        if not a:
            continue
        px = bars[i]["close"]
        sl = px - ba.SL_ATR_MULT * a if side == "buy" else px + ba.SL_ATR_MULT * a
        tp = px + ba.TP_ATR_MULT * a if side == "buy" else px - ba.TP_ATR_MULT * a
        nxt = bars[i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            rows.append(dict(side=side, hold=0, why="entry-bar SL",
                             atr=a, pnl=raw * dpu - cost))
            busy_until = i + 1
            continue
        start = i + 2
        last = eng.n - 1 if not cap else min(eng.n - 1, start + cap - 1)
        if trailing:
            exit_px, exit_i, _m = ba.walk_exit_trail(side, entry, sl, tp, a,
                                                     bars, start)
            why = "trail"
            if cap:
                if exit_i > last:
                    exit_i, exit_px, why = last, bars[last]["close"], "cap"
                else:
                    why = "trail/SL"
        else:
            exit_i = start
            while exit_i < last:
                b = bars[exit_i]
                if side == "buy":
                    if b["low"] <= sl:
                        exit_px, why = sl, "SL"
                        break
                    if b["high"] >= tp:
                        exit_px, why = tp, "TP"
                        break
                else:
                    if b["high"] >= sl:
                        exit_px, why = sl, "SL"
                        break
                    if b["low"] <= tp:
                        exit_px, why = tp, "TP"
                        break
                exit_i += 1
            else:
                exit_px, why = bars[last]["close"], "cap"
        raw = (exit_px - entry) if side == "buy" else (entry - exit_px)
        rows.append(dict(side=side, hold=exit_i - start + 1, why=why, atr=a,
                         pnl=raw * dpu - cost))
        busy_until = exit_i
    return rows


def summarize(rows):
    if not rows:
        return "n=0 net=+0.00"
    net = sum(r["pnl"] for r in rows)
    wins = sum(1 for r in rows if r["pnl"] > 0)
    gl = abs(sum(r["pnl"] for r in rows if r["pnl"] <= 0))
    pf = (sum(r["pnl"] for r in rows if r["pnl"] > 0) / gl) if gl else 999
    return ("n=%-3d net=%+8.2f win=%2.0f%% PF=%.2f avg_hold=%4.1f"
            % (len(rows), net, 100.0 * wins / len(rows), pf,
               sum(r["hold"] for r in rows) / float(len(rows))))


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
        emit("mt5.initialize failed")
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
    emit("AETHERFLOW-M30 DIAGNOSIS -- %s demo | cost $%.2f/trade | UT-only"
         % (acc.login, cost))

    feeds = {
        "M30 (true feed, what the LIVE twin 950002/960002 runs on)":
            closed_bars("XAUUSD", "M30", 100 * 48 + 320),
        "H4 (the feed the trail-config sweep actually used)":
            closed_bars("XAUUSD", "H4", 100 * 6 + 320),
    }

    for label, bars in feeds.items():
        if len(bars) < 300:
            emit("\n%s: not enough bars (%d)" % (label, len(bars)))
            continue
        eng = ba.Engines(bars)
        emit("\n================ FEED: %s (%d bars) ================" % (label, len(bars)))

        emit("\n-- CONTROL: reproduce the uncapped numbers (cap=0) --")
        for act, dist, step, tag in TRAILS:
            ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
            for trailing in (False, True):
                rows = run_detail(eng, bars, dpu, cost, "ut", trailing, 0)
                emit("   %-22s %-6s %s"
                     % (tag, "trail" if trailing else "fixed",
                        summarize(rows)))

        emit("\n-- PER-TRADE DETAIL, deployed trail, cap=0 (why it loses) --")
        ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = 0.2, 0.5, 0.10
        rows = run_detail(eng, bars, dpu, cost, "ut", True, 0)
        emit("   %-6s %-4s %-5s %-8s %-7s %s"
             % ("side", "hold", "exit", "atr", "pnl", "bar_time"))
        for r in sorted(rows, key=lambda x: x["pnl"])[:18]:
            emit("   %-6s %-4d %-12s %-8.3f %+7.2f"
                 % (r["side"], r["hold"], r["why"], r["atr"], r["pnl"]))
        if rows:
            holds = [r["hold"] for r in rows]
            losers = [r for r in rows if r["pnl"] <= 0]
            emit("   hold range %d..%d | losers avg hold %.1f vs winners %.1f"
                 % (min(holds), max(holds),
                    (sum(r["hold"] for r in losers) / float(len(losers)))
                    if losers else 0.0,
                    (sum(r["hold"] for r in rows if r["pnl"] > 0)
                     / float(max(1, len([r for r in rows if r["pnl"] > 0]))))))

        emit("\n-- TIME-CAP SWEEP (the lever that rescued H4) --")
        emit("   %-22s %-6s %s" % ("config", "mode", "  ".join(
            ("cap%d" % c).rjust(22) for c in CAPS)))
        for act, dist, step, tag in TRAILS:
            ba.TRAIL_ACTIVATE, ba.TRAIL_DIST, ba.TRAIL_STEP = act, dist, step
            for trailing in (False, True):
                cells = []
                for c in CAPS:
                    rr = run_detail(eng, bars, dpu, cost, "ut", trailing, c)
                    cells.append(summarize(rr).rjust(22))
                emit("   %-22s %-6s %s"
                     % (tag, "trail" if trailing else "fixed", "  ".join(cells)))

    mt5.shutdown()
    emit("\n-> C:/FTTest/logs/aetherflow_m30.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())