#!/usr/bin/env python3
"""Market analysis via the guarded MetaTrader MCP launcher.

Two reports in one session:
  1. ATR trend-breakout backtest on XAUUSD H1 (equity curve, max drawdown).
  2. StraddleV2 EA (magic 778001) deep analysis: daily P&L/drawdown, session
     breakdown, and behavior in news-spike hours (widest 5% H1 ranges).

Spawns the MCP server exactly like .agents/mcp.json does (`python` + relative
path), so it also verifies the portable config. Never launches MT5 itself.

Usage: python scripts/market_analysis.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EA_MAGIC = 778001  # StraddleV2
START_EQUITY = 2000.0
LOTS = 0.01        # 0.01 lot XAUUSD = 1 oz -> $1 per $1 price move
COMM_RT = 0.04     # round-trip commission per 0.01 lot
N, ATR_N = 20, 14  # Donchian lookback, ATR period


def parse_t(s):
    s = (s or "").strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.utcfromtimestamp(int(s))
        except Exception:
            return None


async def fetch(session, tool, args):
    result = await session.call_tool(tool, args)
    return result.content[0].text


async def main():
    params = StdioServerParameters(
        command="python",
        args=["scripts/mt5_mcp_guarded.py", "--transport", "stdio"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("PORTABLE SPAWN OK (python + relative path, like .agents/mcp.json)")

            hist_csv = await fetch(session, "get_deals", {
                "from_date": "2026-08-25",
                "to_date": str(date.today() + timedelta(days=2)),
            })
            hist = list(csv.DictReader(io.StringIO(hist_csv)))

            bars = []
            for count in (4000, 1500, 500):
                candles_csv = await fetch(session, "get_candles_latest",
                                          {"symbol_name": "XAUUSD", "timeframe": "H1", "count": count})
                bars = list(csv.DictReader(io.StringIO(candles_csv)))
                if len(bars) > 100:
                    break
            print(f"CANDLES: {len(bars)} XAUUSD H1 bars fetched (requested {count})")

    f = lambda r, k: float(r.get(k) or 0)
    for b in bars:
        b["t"] = parse_t(b.get("time"))
        for k in ("open", "high", "low", "close"):
            b[k] = float(b[k])
        b["spread"] = float(b.get("spread") or 0)
    bars = [b for b in bars if b["t"]]
    bars.sort(key=lambda b: b["t"])
    if bars:
        print(f"  range: {bars[0]['t']} .. {bars[-1]['t']}")

    # ============ PART 1: ATR trend-breakout backtest ============
    avg_spread_cost = (sum(b["spread"] for b in bars) / len(bars)) * 0.01 if bars else 0.15

    trs = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, len(bars)):
        p = bars[i - 1]
        trs.append(max(bars[i]["high"] - bars[i]["low"],
                       abs(bars[i]["high"] - p["close"]), abs(bars[i]["low"] - p["close"])))

    def atr(i):
        lo = max(1, i - ATR_N + 1)
        return sum(trs[lo:i + 1]) / (i - lo + 1)

    trades, equity = [], [START_EQUITY]
    pos = None
    for i in range(N, len(bars)):
        b = bars[i]
        hh = max(x["high"] for x in bars[i - N:i])
        ll = min(x["low"] for x in bars[i - N:i])
        a = atr(i - 1)
        if pos:
            exit_px, reason = None, None
            if pos["dir"] == 1:
                if b["low"] <= pos["sl"]:
                    exit_px, reason = pos["sl"], "SL"  # pessimistic: SL first
                elif b["high"] >= pos["tp"]:
                    exit_px, reason = pos["tp"], "TP"
            else:
                if b["high"] >= pos["sl"]:
                    exit_px, reason = pos["sl"], "SL"
                elif b["low"] <= pos["tp"]:
                    exit_px, reason = pos["tp"], "TP"
            if exit_px is not None:
                pnl = (exit_px - pos["entry"]) * pos["dir"] * 100 * LOTS - COMM_RT - avg_spread_cost
                trades.append(dict(pnl=pnl, reason=reason, t=b["t"]))
                equity.append(equity[-1] + pnl)
                pos = None
            elif (pos["dir"] == 1 and b["close"] < ll) or (pos["dir"] == -1 and b["close"] > hh):
                pnl = (b["close"] - pos["entry"]) * pos["dir"] * 100 * LOTS - COMM_RT - avg_spread_cost
                trades.append(dict(pnl=pnl, reason="REV", t=b["t"]))
                equity.append(equity[-1] + pnl)
                pos = None
        if pos is None:
            if b["close"] > hh:
                pos = dict(dir=1, entry=b["close"], sl=b["close"] - 2 * a, tp=b["close"] + 3 * a)
            elif b["close"] < ll:
                pos = dict(dir=-1, entry=b["close"], sl=b["close"] + 2 * a, tp=b["close"] - 3 * a)
    if pos:
        b = bars[-1]
        pnl = (b["close"] - pos["entry"]) * pos["dir"] * 100 * LOTS - COMM_RT - avg_spread_cost
        trades.append(dict(pnl=pnl, reason="EOD", t=b["t"]))
        equity.append(equity[-1] + pnl)

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    peak, mdd, mdd_pct = equity[0], 0.0, 0.0
    for e in equity:
        peak = max(peak, e)
        dd = peak - e
        if dd > mdd:
            mdd, mdd_pct = dd, 100 * dd / peak
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")
    monthly = defaultdict(float)
    for t in trades:
        monthly[t["t"].strftime("%Y-%m")] += t["pnl"]
    eq_by_week = defaultdict(float)
    for t in trades:
        eq_by_week[t["t"].strftime("%W")] += t["pnl"]
    run, pts = START_EQUITY, []
    for w in sorted(eq_by_week):
        run += eq_by_week[w]
        pts.append(run)
    spark = "_.:-=+*#"  # ASCII ramp (Windows console is cp1252)
    lo, hi = min(pts + [START_EQUITY]), max(pts + [START_EQUITY])
    curve = "".join(spark[min(7, int((p - lo) / (hi - lo + 1e-9) * 7.999))] for p in pts) if pts else ""

    print("\n================ ATR TREND-BREAKOUT BACKTEST (XAUUSD H1) ================")
    print(f"rules: Donchian-{N} breakout of prior bar extremes, ATR({ATR_N}) stops")
    print("  long/short on close beyond 20-bar extreme; SL=2*ATR, TP=3*ATR; reverse on opposite signal")
    print(f"  fixed {LOTS} lot (1 oz); costs: commission ${COMM_RT}/rt + spread ~${avg_spread_cost:.2f}/trade")
    if trades:
        print(f"bars: {len(bars)}   trades: {len(trades)}   win rate: {100 * len(wins) / len(pnls):.1f}%")
        print(f"net P&L: {equity[-1] - START_EQUITY:+.2f}  final equity: {equity[-1]:.2f}  profit factor: {pf:.2f}")
        if wins and losses:
            print(f"avg win {sum(wins) / len(wins):+.2f} / avg loss {sum(losses) / len(losses):+.2f}")
        print(f"MAX DRAWDOWN: {mdd:.2f} ({mdd_pct:.1f}%)")
        print("monthly net:", {k: round(v, 2) for k, v in sorted(monthly.items())})
        print("equity curve (weekly):", curve)
    else:
        print("no trades generated")

    # ============ PART 2: StraddleV2 EA deep analysis ============
    posmap = defaultdict(lambda: dict(pnl=0.0, magic=0, symbol="", close_t=None, open_t=None, exit=""))
    for r in hist:
        pid = r.get("position_id", "0")
        if not pid or pid == "0" or not r.get("symbol"):
            continue
        t = posmap[pid]
        t["pnl"] += f(r, "profit") + f(r, "commission") + f(r, "swap") + f(r, "fee")
        t["magic"] = int(float(r.get("magic") or 0))
        t["symbol"] = r["symbol"]
        ot = parse_t(r.get("time"))
        if t["open_t"] is None or (ot and ot < t["open_t"]):
            t["open_t"] = ot
        if r.get("entry") in ("1", "2", "3"):
            t["close_t"] = ot
            t["exit"] = r.get("comment", "")
    ea = {k: v for k, v in posmap.items() if v["magic"] != 0 and v["close_t"]}
    by_magic = defaultdict(lambda: [0, 0.0])
    for v in ea.values():
        by_magic[v["magic"]][0] += 1
        by_magic[v["magic"]][1] += v["pnl"]
    print("\nBY MAGIC NUMBER:")
    for m, (n, p) in sorted(by_magic.items(), key=lambda kv: -kv[1][0]):
        print(f"  magic {m}: n={n:5d}  net={p:+8.2f}  avg={p / n:+.3f}")

    daily = defaultdict(lambda: [0, 0.0])
    hourly = defaultdict(lambda: [0, 0.0])
    for v in ea.values():
        d = v["close_t"].date()
        daily[d][0] += 1
        daily[d][1] += v["pnl"]
        h = v["open_t"].hour if v["open_t"] else v["close_t"].hour
        hourly[h][0] += 1
        hourly[h][1] += v["pnl"]

    # Stress-window ("news spike") analysis - timezone-safe, deals only:
    # stress events are max-loss trades (worst 0.5%, at most -2.00); window = +/-45 min.
    ordered = sorted(ea.values(), key=lambda v: v["close_t"])
    thresh = sorted(v["pnl"] for v in ordered)[max(0, int(len(ordered) * 0.005))]
    events = [v for v in ordered if v["pnl"] <= min(thresh, -2.0)]
    windows = [(v["close_t"] - timedelta(minutes=45), v["close_t"] + timedelta(minutes=45)) for v in events]
    in_stress = lambda t: any(lo <= t <= hi for lo, hi in windows)
    spike = [v["pnl"] for v in ordered if in_stress(v["close_t"])]
    normal = [v["pnl"] for v in ordered if not in_stress(v["close_t"])]

    cum, peak, mdd_d, dd_lo, dd_hi, cur_lo = 0.0, 0.0, 0.0, None, None, None
    for d in sorted(daily):
        cum += daily[d][1]
        if cum > peak:
            peak, cur_lo = cum, d
        if peak - cum > mdd_d:
            mdd_d = peak - cum
            dd_lo, dd_hi = cur_lo, d

    print("\n================ STRADDLEV2 EA (magic %d) DEEP ANALYSIS ================" % EA_MAGIC)
    print(f"closed EA trades in window: {len(ea)}   net: {sum(v['pnl'] for v in ea.values()):+.2f}")
    print("\nDAILY NET P&L (server dates):")
    run = 0.0
    for d in sorted(daily):
        run += daily[d][1]
        bar = ("+" if daily[d][1] > 0 else "-") * min(40, max(1, int(abs(daily[d][1]))))
        print(f"  {d}  n={daily[d][0]:4d}  net={daily[d][1]:+8.2f}  cum={run:+9.2f}  {bar}")
    print(f"MAX DRAWDOWN (daily-cumulative): {mdd_d:.2f} USD  ({dd_lo} -> {dd_hi})")
    worst_day = min(daily.items(), key=lambda kv: kv[1][1])
    best_day = max(daily.items(), key=lambda kv: kv[1][1])
    print(f"worst day: {worst_day[0]} ({worst_day[1][1]:+.2f} on {worst_day[1][0]} trades)")
    print(f"best day:  {best_day[0]} ({best_day[1][1]:+.2f} on {best_day[1][0]} trades)")

    def bucket(h):
        return "Asia 00-06" if h < 7 else "Europe 07-12" if h < 13 else "US 13-18" if h < 19 else "Late 19-23"

    bk = defaultdict(lambda: [0, 0.0])
    for h, (n, p) in hourly.items():
        b_ = bk[bucket(h)]
        b_[0] += n
        b_[1] += p
    print("\nBY SESSION (trade open hour, server time):")
    for name in ("Asia 00-06", "Europe 07-12", "US 13-18", "Late 19-23"):
        n, p = bk[name]
        if n:
            print(f"  {name}: n={n:5d}  net={p:+8.2f}  avg={p / n:+.3f}")
    print("\nBY HOUR (3 worst / 3 best):")
    hs = sorted(hourly.items(), key=lambda kv: kv[1][1])
    for h, (n, p) in hs[:3] + hs[-3:]:
        print(f"  hour {h:02d}: n={n:4d} net={p:+7.2f}")

    def agg(xs):
        return (len(xs), sum(xs),
                100 * sum(1 for p in xs if p > 0) / len(xs) if xs else 0.0,
                sum(xs) / len(xs) if xs else 0.0)

    sn, sp, swr, savg = agg(spike)
    nn, np_, nwr, navg = agg(normal)
    print(f"\nNEWS-SPIKE / STRESS-WINDOW BEHAVIOR (window = max-loss events +/- 45 min, events={len(events)}):")
    print(f"  trades inside stress windows:  {sn}  net={sp:+.2f}  win%={swr:.1f}  avg={savg:+.3f}")
    print(f"  trades outside (normal):       {nn}  net={np_:+.2f}  win%={nwr:.1f}  avg={navg:+.3f}")
    merged = []
    for lo, hi in sorted(windows):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    print("  top stress windows:")
    for lo, hi in merged[:5]:
        inside = [v for v in ordered if lo <= v["close_t"] <= hi]
        print(f"    {lo} .. {hi}: n={len(inside)} net={sum(v['pnl'] for v in inside):+.2f}")
    worst = sorted(ea.values(), key=lambda v: v["pnl"])[:5]
    print("  worst 5 trades:")
    for v in worst:
        print(f"    {v['close_t']}  {v['pnl']:+.2f}  magic={v['magic']}  exit={v['exit']}")
    streak, worst_streak, worst_sum, cur = 0, 0, 0.0, 0.0
    for v in ordered:
        if v["pnl"] <= 0:
            streak += 1
            cur += v["pnl"]
            worst_streak = max(worst_streak, streak)
            worst_sum = min(worst_sum, cur)
        else:
            streak, cur = 0, 0.0
    print(f"  worst losing streak: {worst_streak} trades ({worst_sum:+.2f} USD)")


if __name__ == "__main__":
    asyncio.run(main())
