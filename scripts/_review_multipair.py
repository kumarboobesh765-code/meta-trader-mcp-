"""One-off: per-pair/per-strategy P&L from the pulled VPS deals.csv + flags.
Usage: python scripts/_review_multipair.py <deals.csv> [runner_stdout.txt]
"""

import csv
import sys
from collections import defaultdict

deals_path = sys.argv[1]
stdout_path = sys.argv[2] if len(sys.argv) > 2 else None

SYMBOL_OF_CODE = {"EUR": "EURUSD", "GBP": "GBPUSD", "JPY": "USDJPY", "AUD": "AUDUSD"}
BASES = ("breakout", "meanrev", "macross", "straddle", "smc", "london", "squeeze")


def parse_name(strategy):
    """'macross-EUR-EA-T' -> ('macross', 'EURUSD', True, True)"""
    trail = strategy.endswith("-T")
    s = strategy[:-2] if trail else strategy
    ea = s.endswith("-EA")
    s = s[:-3] if ea else s
    for code, sym in SYMBOL_OF_CODE.items():
        if s.endswith("-" + code):
            return s[: -(len(code) + 1)], sym, trail, ea
    return s, "XAUUSD", trail, ea


rows = list(csv.DictReader(open(deals_path, newline="")))
multi = [r for r in rows if any(r["strategy"].endswith("-" + c) for c in SYMBOL_OF_CODE)]

per = defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0})
open_pos = defaultdict(float)   # position_id -> realized so far ('in' deals)
per_pos_net = defaultdict(float)

for r in rows:
    p = r["position_id"]
    net = float(r["profit"]) + float(r["commission"]) + float(r["swap"])
    per_pos_net[p] += net
    if r["entry"] == "out":
        base, sym, trail, ea = parse_name(r["strategy"])
        net = per_pos_net[p]     # full round trip
        k = per[(sym, base + ("-EA" if ea else ""), trail)]
        k["n"] += 1
        k["net"] += net
        k["wins"] += 1 if net > 0 else 0

# the multi-pair test only started at 17:25 today; most positions are still open,
# so ALSO show floating P&L per (pair, strategy) from the runner stdout snapshot
print("=== CLOSED round-trips since multi-pair start (17:25 today) ===")
if not multi:
    print("(none yet -- positions from 17:25 are still open)")
for (sym, base, trail), k in sorted(per.items()):
    if sym == "XAUUSD":
        continue
    tag = base + ("-T" if trail else "")
    print("%-8s %-10s n=%-3d net=%+8.2f win%%=%5.1f"
          % (sym, tag, k["n"], k["net"], 100.0 * k["wins"] / max(k["n"], 1)))

print()
print("=== Runner stdout: errors / failures since STARTED ===")
if stdout_path:
    started = False
    fails = defaultdict(int)
    examples = {}
    for line in open(stdout_path, errors="replace"):
        if "STARTED" in line and "5 symbols" in line:
            started = True
            continue
        if not started:
            continue
        if "FAILED" in line or "failed" in line or "loop error" in line:
            for token in ("retcode=10012", "retcode=10015", "retcode=10016",
                          "retcode=10004", "loop error"):
                if token in line:
                    fails[token] += 1
                    examples.setdefault(token, line.strip())
    for tok, n in sorted(fails.items(), key=lambda kv: -kv[1]):
        print("%-16s x%-4d e.g. %s" % (tok, n, examples[tok][:90]))
    if not fails:
        print("(clean: no order failures or loop errors since 17:25)")

print()
print("=== Multi-pair deals logged so far ===")
mp = [r for r in rows if any(r["strategy"].endswith("-" + c) for c in SYMBOL_OF_CODE)]
by_strat = defaultdict(lambda: [0, 0.0])
pos_strat = {}
for r in mp:
    if r["entry"] == "in":
        pos_strat[r["position_id"]] = r["strategy"]
    else:
        s = pos_strat.get(r["position_id"], r["strategy"])
    s = r["strategy"]
    by_strat[s][0] += 1
    by_strat[s][1] += float(r["profit"]) + float(r["commission"]) + float(r["swap"])
for s in sorted(by_strat):
    n, net = by_strat[s]
    print("%-14s deals=%-4d dealPnL=%+9.2f" % (s, n, net))
