"""Per-EA live roster + performance summary (2026-09-30). Read-only.

Roster = the 31 charts live since the 2026-09-30 rebuild (supertrend added,
meanrev/profile retired). Per magic: closed trips from deals.csv (all-time
session log), net, PF, win%, today's net, and floating P&L of any open
position via the live account attach.

Run: python C:/FTTest/scripts/_ea_roster_20260930.py
"""
import csv
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from forward_test import load_env, MAGICS

DEALS = r"C:\FTTest\logs\forward\deals.csv"
LIVE = r"C:\FTTest\logs\live.json"

# charts live since 2026-09-30 (meanrev 930002/940002 + profile 930008/940008
# retired; magics kept in MAGICS so history keeps logging)
LIVE_EAS = [
    (930001, "breakout"), (940001, "breakout-T"),
    (930003, "macross"), (940003, "macross-T"),
    (930004, "straddle"), (940004, "straddle-T"),
    (930005, "smc"), (940005, "smc-T"),
    (930006, "london"), (940006, "london-T"),
    (930007, "squeeze"), (940007, "squeeze-T"),
    (930009, "orderflow"), (940009, "orderflow-T"),
    (930010, "trendpullback"), (940010, "trendpullback-T"),
    (930011, "donchian"), (940011, "donchian-T"),
    (930012, "trend"), (940012, "trend-T"),
    (930013, "supres"), (940013, "supres-T"),
    (930014, "supertrend"), (940014, "supertrend-T"),
    (950001, "aetherflow"), (960001, "aetherflow-T"),
    (950002, "aetherflow-M30"), (960002, "aetherflow-M30-T"),
    (950003, "aetherflow-H4"), (960003, "aetherflow-H4-T"),
    (26092501, "smvp"),
]
RETIRED = [(930002, "meanrev (RETIRED)"), (940002, "meanrev-T (RETIRED)"),
           (930008, "profile (RETIRED)"), (940008, "profile-T (RETIRED)")]


def main():
    load_env()
    for attempt in range(4):
        if mt5.initialize():
            break
        print("attach attempt %d failed: %s" % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        time.sleep(8)
    else:
        print("ATTACH_FAILED -- falling back to deals.csv/live.json only")
    acc = mt5.account_info()
    positions = mt5.positions_get() or []
    all_deals = mt5.history_deals_get(time.time() - 45 * 86400,
                                      time.time() + 4 * 3600) or []
    mt5.shutdown()

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # trips per magic from deals.csv (append-only log)
    trips = {}      # magic -> [n, net, wins]
    today = {}      # magic -> net today
    pos = {}        # position_id -> entry row
    if os.path.exists(DEALS):
        with open(DEALS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    m = int(r["magic"])
                    p = float(r["profit"]) + float(r["commission"]) + float(r["swap"])
                except (ValueError, KeyError):
                    continue
                if r["entry"] == "in":
                    pos[r["position_id"]] = (m, r)
                elif r["entry"] == "out" and r["position_id"] in pos:
                    t = trips.setdefault(m, [0, 0.0, 0])
                    t[0] += 1
                    t[1] += p
                    t[2] += 1 if p > 0 else 0
                    if r["time_utc"][:10] == day:
                        today[m] = today.get(m, 0.0) + p

    # live mt5 history for anything deals.csv missed (fresh EA trades)
    for d in all_deals:
        if d.magic not in MAGICS:
            continue
        if d.entry == 1:  # DEAL_ENTRY_OUT
            t = trips.setdefault(d.magic, [0, 0.0, 0])
            p = d.profit + d.commission + d.swap
            ts = datetime.fromtimestamp(d.time, timezone.utc).strftime("%Y-%m-%d")
            if ts == day:
                today[d.magic] = today.get(d.magic, 0.0) + p
            if t[0] == 0:
                t[0] += 1
                t[1] += p
                t[2] += 1 if p > 0 else 0

    floating = {}
    for p in positions:
        floating[p.magic] = floating.get(p.magic, 0.0) + p.profit + p.swap

    if acc is not None:
        print("ACCOUNT %s %s | bal=%.2f eq=%.2f | open=%d floating=%+.2f"
              % (acc.login, acc.server, acc.balance, acc.equity,
                 len(positions), acc.equity - acc.balance))
    else:
        try:
            import json
            lv = json.load(open(LIVE, encoding="utf-8"))
            print("ACCOUNT (live.json) | bal=%s eq=%s | open=%s"
                  % (lv.get("bal"), lv.get("eq"), lv.get("open")))
        except Exception:
            pass
    print("=== LIVE EA ROSTER (%d EAs) | session-to-date from deals.csv + live floating ==="
          % len(LIVE_EAS))
    print("%-20s %6s %10s %7s %7s %10s %10s"
          % ("EA", "trips", "net", "PF", "win%", "today", "floating"))
    rows = []
    for m, name in LIVE_EAS:
        n, net, wins = trips.get(m, [0, 0.0, 0])
        gw = net + sum(x for x in [0])  # pf needs gross loss; recompute below
        rows.append((net, name, m, n, wins))
    # PF needs gross win / gross loss -> second pass
    trip_pnl = {}
    if os.path.exists(DEALS):
        with open(DEALS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["entry"] != "out":
                    continue
                try:
                    m = int(r["magic"])
                    p = float(r["profit"]) + float(r["commission"]) + float(r["swap"])
                except (ValueError, KeyError):
                    continue
                trip_pnl.setdefault(m, []).append(p)
    for net, name, m, n, wins in sorted(rows, key=lambda x: -x[0]):
        pnl = trip_pnl.get(m, [])
        gw = sum(x for x in pnl if x > 0)
        gl = abs(sum(x for x in pnl if x <= 0))
        pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
        w = 100.0 * wins / n if n else 0.0
        print("%-20s %6d %+10.2f %7s %6.0f%% %+10.2f %+10.2f"
              % (name, n, net, pf, w, today.get(m, 0.0), floating.get(m, 0.0)))

    tot_flt = sum(floating.get(m, 0.0) for m, _ in LIVE_EAS)
    print("%-20s %6d %+10.2f" % ("TOTAL (live EAs)",
                                 sum(trips.get(m, [0])[0] for m, _ in LIVE_EAS),
                                 sum(trips.get(m, [0, 0.0])[1] for m, _ in LIVE_EAS)))
    print("floating (live EAs): %+.2f" % tot_flt)

    print("\n=== RETIRED (history kept for the log) ===")
    for m, name in RETIRED:
        pnl = trip_pnl.get(m, [])
        n, net, wins = trips.get(m, [0, 0.0, 0])
        gw = sum(x for x in pnl if x > 0)
        gl = abs(sum(x for x in pnl if x <= 0))
        pf = ("%.2f" % (gw / gl)) if gl > 0 else "inf"
        w = 100.0 * wins / n if n else 0.0
        print("%-24s %6d %+10.2f %7s %6.0f%%" % (name, n, net, pf, w))
    return 0


if __name__ == "__main__":
    sys.exit(main())
