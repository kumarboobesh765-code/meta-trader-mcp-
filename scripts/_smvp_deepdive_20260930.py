"""smvp deep-dive (2026-09-30): every closed trip, realized risk stats,
equity curve, journal health -> input for the keep-or-raise 0.25% decision.
Read-only. Run: python C:/FTTest/scripts/_smvp_deepdive_20260930.py
"""
import csv
import glob
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from forward_test import load_env

DEALS = r"C:\FTTest\logs\forward\deals.csv"
DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
MAGIC = 26092501
NAME = "smvp"


def journal_stats(days=3):
    now = time.time()
    s = {"open": 0, "trail": 0, "close": 0, "stuck": 0, "err": []}
    for sub in ("logs", os.path.join("MQL5", "Logs")):
        for j in glob.glob(os.path.join(DATA, sub, "*.log")):
            if now - os.path.getmtime(j) > days * 86400:
                continue
            try:
                if os.path.getsize(j) > 40e6:
                    continue
                try:
                    txt = open(j, encoding="utf-16", errors="replace").read()
                except UnicodeError:
                    txt = open(j, encoding="cp1252", errors="replace").read()
            except OSError:
                continue
            for line in txt.splitlines():
                if str(MAGIC) not in line:
                    continue
                if "trail SL ->" in line:
                    s["trail"] += 1
                elif " OPEN " in line:
                    s["open"] += 1
                elif " CLOSE " in line or "CLOSE #" in line:
                    s["close"] += 1
                elif "STUCK-STOP" in line:
                    s["stuck"] += 1
                elif re.search(r"failed|error|invalid", line, re.I):
                    s["err"].append(line.strip()[:120])
    return s


def main():
    load_env()
    for attempt in range(4):
        if mt5.initialize():
            break
        mt5.shutdown()
        time.sleep(6)
    acc = mt5.account_info()
    bal = acc.balance if acc else None
    poss = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    all_deals = mt5.history_deals_get(time.time() - 45 * 86400,
                                      time.time() + 4 * 3600) or []
    mt5.shutdown()

    print("=== smvp (%d) deep-dive | balance %s ===" % (MAGIC, bal))
    print("\n-- open positions: %d --" % len(poss))
    for p in poss:
        print("  #%d %s vol=%.2f entry=%.2f sl=%.2f tp=%.2f float=%+.2f"
              % (p.ticket, "BUY" if p.type == 0 else "SELL", p.volume,
                 p.price_open, p.sl, p.tp, p.profit + p.swap))

    # trips from deals.csv (log of record) + mt5 history fallback
    trips = []
    pos_in = {}
    if os.path.exists(DEALS):
        with open(DEALS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r["magic"]) != MAGIC:
                        continue
                except ValueError:
                    continue
                if r["entry"] == "in":
                    pos_in[r["position_id"]] = r
                elif r["entry"] == "out" and r["position_id"] in pos_in:
                    i = pos_in.pop(r["position_id"])
                    pnl = float(r["profit"] or 0) + float(r["commission"] or 0) \
                        + float(r["swap"] or 0)
                    t_in = datetime.fromisoformat(i["time_utc"])
                    t_out = datetime.fromisoformat(r["time_utc"])
                    trips.append({
                        "side": i["type"], "vol": float(i["volume"]),
                        "in_px": float(i["price"]), "out_px": float(r["price"]),
                        "in_t": t_in, "out_t": t_out,
                        "hold_h": (t_out - t_in).total_seconds() / 3600.0,
                        "pnl": pnl})
    if not trips:
        for d in all_deals:
            if d.magic != MAGIC:
                continue
            if d.entry == 0:
                pos_in[d.position_id] = d
            elif d.entry == 1 and d.position_id in pos_in:
                i = pos_in.pop(d.position_id)
                trips.append({"side": "buy" if i.type == 0 else "sell",
                              "vol": i.volume, "in_px": i.price,
                              "out_px": d.price,
                              "in_t": datetime.fromtimestamp(i.time, timezone.utc),
                              "out_t": datetime.fromtimestamp(d.time, timezone.utc),
                              "hold_h": (d.time - i.time) / 3600.0,
                              "pnl": d.profit + d.commission + d.swap})
    trips.sort(key=lambda t: t["in_t"])

    print("\n-- all %d closed trips --" % len(trips))
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    print("%-17s %-4s %5s %9s %9s %7s %8s %8s"
          % ("entry (UTC)", "side", "lots", "in", "out", "hold_h", "pnl", "eq"))
    for t in trips:
        eq += t["pnl"]
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
        print("%-17s %-4s %5.2f %9.2f %9.2f %7.1f %+8.2f %+8.2f"
              % (t["in_t"].strftime("%m-%d %H:%M"), t["side"], t["vol"],
                 t["in_px"], t["out_px"], t["hold_h"], t["pnl"], eq))

    wins = [t for t in trips if t["pnl"] > 0]
    losses = [t for t in trips if t["pnl"] <= 0]
    net = sum(t["pnl"] for t in trips)
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = (gw / gl) if gl > 0 else float("inf")
    avg_w = gw / len(wins) if wins else 0.0
    avg_l = gl / len(losses) if losses else 0.0
    worst = min(trips, key=lambda t: t["pnl"]) if trips else None
    vols = sorted(set(t["vol"] for t in trips))
    print("\n-- stats --")
    print("  net %+.2f | PF %s | win %d/%d (%.0f%%)"
          % (net, ("%.2f" % pf) if pf != float("inf") else "inf",
             len(wins), len(trips), 100.0 * len(wins) / max(1, len(trips))))
    print("  avg win %+.2f | avg loss %+.2f | payoff %.2f | worst trip %+0.2f"
          % (avg_w, -avg_l, (avg_w / avg_l) if avg_l else 0,
             worst["pnl"] if worst else 0))
    print("  max trip-sequence drawdown: $%.2f" % max_dd)
    print("  lots used: %s | avg hold %.1f h"
          % (vols, sum(t["hold_h"] for t in trips) / max(1, len(trips))))
    if bal and worst:
        print("  worst trip = %.2f%% of balance (risk budget 0.25%% = $%.2f)"
              % (100.0 * abs(worst["pnl"]) / bal, bal * 0.0025))

    js = journal_stats(3)
    print("\n-- journal (3d): opens=%d trail-mods=%d closes=%d stuck-guard=%d --"
          % (js["open"], js["trail"], js["close"], js["stuck"]))
    for e in js["err"][-5:]:
        print("   err:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
