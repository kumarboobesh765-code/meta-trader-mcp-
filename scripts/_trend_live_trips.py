"""Trend-family live round trips from deals.csv + stats (retire-or-fix check).

Runs ON THE VPS. Read-only. Filters deals.csv to the trend family only
(strategy in trend-EA / trend-EA-T), pairs in/out by (magic, position_id),
prints per-trip table + overall/twin/side/day stats.
"""
import csv
from collections import defaultdict
from datetime import datetime

DEALS = r"C:\FTTest\logs\forward\deals.csv"
KEEP = ("trend-EA", "trend-EA-T")

rows = []
with open(DEALS, newline="") as f:
    rd = csv.DictReader(f)
    cols = rd.fieldnames
    for row in rd:
        if row.get("strategy") in KEEP:
            rows.append(row)
print("deals.csv cols: %s" % ",".join(cols or []))
print("trend-family deal rows: %d" % len(rows))

opens, trips = {}, []
for r in rows:
    key = (r["magic"], r["position_id"])
    try:
        pnl = float(r["profit"]) + float(r["commission"]) + float(r["swap"])
        t = datetime.fromisoformat(r["time_utc"])
        px = float(r["price"])
        vol = float(r["volume"])
    except (KeyError, ValueError):
        continue
    if r["entry"] == "in":
        opens[key] = {"t": t, "side": r["type"], "px": px, "vol": vol,
                      "strategy": r["strategy"]}
    elif r["entry"] == "out":
        o = opens.pop(key, None)
        if o is None:
            continue
        trips.append({"strategy": r["strategy"], "magic": r["magic"],
                      "t_in": o["t"], "t_out": t, "side": o["side"],
                      "px_in": o["px"], "px_out": px, "vol": vol, "pnl": pnl,
                      "dur_h": (t - o["t"]).total_seconds() / 3600.0})
trips.sort(key=lambda x: x["t_out"])


def stats(ts):
    if not ts:
        return None
    net = sum(t["pnl"] for t in ts)
    wins = [t for t in ts if t["pnl"] > 0]
    loss = [t for t in ts if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in loss))
    return {"n": len(ts), "net": net, "win": 100.0 * len(wins) / len(ts),
            "pf": (gw / gl) if gl else float("inf"), "avg": net / len(ts),
            "avg_w": gw / len(wins) if wins else 0.0,
            "avg_l": -gl / len(loss) if loss else 0.0}


s = stats(trips)
print("\nLIVE trend trips: n=%d net=%+.2f avg=%+.2f win=%.0f%% PF=%.2f "
      "avgW=%+.2f avgL=%+.2f" % (s["n"], s["net"], s["avg"], s["win"],
                                 s["pf"], s["avg_w"], s["avg_l"]))
for name in KEEP:
    ts = [t for t in trips if t["strategy"] == name]
    s2 = stats(ts)
    if s2:
        print("  %-11s n=%d net=%+.2f avg=%+.2f win=%.0f%% PF=%.2f"
              % (name, s2["n"], s2["net"], s2["avg"], s2["win"], s2["pf"]))
for side in ("buy", "sell"):
    ts = [t for t in trips if t["side"].lower() == side]
    s2 = stats(ts)
    if s2:
        print("  %-11s n=%d net=%+.2f avg=%+.2f win=%.0f%%"
              % (side.upper(), s2["n"], s2["net"], s2["avg"], s2["win"]))

print("\nper trip (out UTC | side | px_in->px_out | dur_h | pnl | stream):")
for t in trips:
    print("%s %-4s %8.2f->%8.2f %5.1fh %+7.2f  %s"
          % (t["t_out"].strftime("%m-%d %H:%M"), t["side"], t["px_in"],
             t["px_out"], t["dur_h"], t["pnl"], t["strategy"]))

day, dn = defaultdict(float), defaultdict(int)
for t in trips:
    d = t["t_out"].strftime("%m-%d")
    day[d] += t["pnl"]
    dn[d] += 1
print("\nby day: " + " | ".join("%s %+.2f (%d)" % (d, day[d], dn[d])
                                for d in sorted(day)))
