"""Overnight watch: hourly snapshot of the 3 grid EAs (930021/22/23).
Appends to C:/FTTest/logs/overnight_3grid_YYYYMMDD.txt. READ-ONLY, never trades.
Scheduled via schtasks on the VPS; expiry set at creation for tomorrow morning.
"""
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from collections import Counter
import os

LOG = "C:/FTTest/logs/overnight_3grid_%s.txt" % datetime.now().strftime("%Y%m%d")

ok = mt5.initialize(timeout=15000)
lines = ["#### %s UTC ####" % datetime.now(timezone.utc).strftime("%m-%d %H:%M:%S")]
if not ok:
    lines.append("INIT_FAIL %s" % (mt5.last_error(),))
else:
    try:
        a = mt5.account_info()
        lines.append("ACCT %s bal=%.2f eq=%.2f" % (a.login, a.balance, a.equity))
        ps = mt5.positions_get() or []
        g = [p for p in ps if p.magic in (930021, 930022, 930023)]
        lines.append("OPEN total=%d grid=%d %s" % (
            len(ps), len(g), dict(sorted(Counter(p.magic for p in g).items()))))
        fl = {}
        for p in g:
            fl.setdefault(p.magic, 0.0)
            fl[p.magic] += p.profit + p.swap
        for m in (930021, 930022, 930023):
            n = sum(1 for p in g if p.magic == m)
            lines.append("  magic=%d n=%d float=%+.2f" % (m, n, fl.get(m, 0.0)))
        now = datetime.now(timezone.utc)
        ds = mt5.history_deals_get(now - timedelta(hours=2),
                                   now + timedelta(minutes=5)) or []
        cl = [d for d in ds if d.magic in (930021, 930022, 930023)
              and d.type in (0, 1) and d.entry == 1]
        if cl:
            net = sum(d.profit + d.commission + d.swap for d in cl)
            lines.append("CLOSED_2h n=%d net=%+.2f %s" % (
                len(cl), net, dict(sorted(Counter(d.magic for d in cl).items()))))
        else:
            lines.append("CLOSED_2h n=0")
    finally:
        mt5.shutdown()
with open(LOG, "a") as f:
    f.write("\n".join(lines) + "\n")
print("wrote %d lines to %s" % (len(lines), LOG), flush=True)
