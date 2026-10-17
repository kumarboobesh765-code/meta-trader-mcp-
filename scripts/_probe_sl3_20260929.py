"""Quantify server-side latency: distribution of 'done in X ms' from today's terminal
journal, SL activation lines, and current state of the 3 stuck sells."""
import os
import re
import glob
import statistics
from datetime import datetime, timezone

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")
UTC = timezone.utc

DUR = re.compile(r"done in ([\d.]+) ms")
ACT = re.compile(r"(stop loss|take profit).*#(\d+)")


def read_journal(path):
    for enc in ("utf-16", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except (UnicodeError, UnicodeDecodeError):
            continue
    return []


durs = []
for day in ("20260928", "20260929"):
    path = os.path.join(LOGS, day + ".log")
    if not os.path.exists(path):
        continue
    for ln in read_journal(path):
        m = DUR.search(ln)
        if m:
            durs.append((day, float(m.group(1)), ln.split("\t")[2][:8] if "\t" in ln else "?",
                         ln.split("\t", 2)[-1][:90]))

print("=== 'done in' durations by day ===")
for day in ("20260928", "20260929"):
    ds = [d[1] for d in durs if d[0] == day]
    if ds:
        ds.sort()
        print(f"{day}: n={len(ds)} median={statistics.median(ds):,.0f}ms p90={ds[int(len(ds)*0.9)]:,.0f}ms "
              f"max={max(ds):,.0f}ms | >5s: {sum(1 for x in ds if x > 5000)} | >30s: {sum(1 for x in ds if x > 30000)}")

print("\n=== slowest 8 ops ===")
for day, ms, t, txt in sorted(durs, key=lambda x: -x[1])[:8]:
    print(f"  {day} {t} {ms:>12,.0f}ms  {txt}")

print("\n=== SL activation lines today (last 12) ===")
acts = []
for ln in read_journal(os.path.join(LOGS, "20260929.log")):
    m = ACT.search(ln.lower())
    if m:
        acts.append(ln.split("\t", 2)[-1].strip())
for a in acts[-12:]:
    print(f"  {a[:150]}")

mt5.initialize()
print("\n=== stuck sells now ===")
open_ids = {p.ticket: p for p in (mt5.positions_get() or [])}
for t in (2103956425, 2103956435, 2104175793):
    p = open_ids.get(t)
    if p:
        print(f"  STILL OPEN #{t} sl={p.sl} cur(ask)={p.price_current} pnl={p.profit:+.2f}")
    else:
        print(f"  closed #{t}")
tick = mt5.symbol_info_tick("XAUUSD")
print(f"tick: bid={tick.bid} ask={tick.ask} time={datetime.fromtimestamp(tick.time, UTC):%H:%M:%S}Z")
mt5.shutdown()
