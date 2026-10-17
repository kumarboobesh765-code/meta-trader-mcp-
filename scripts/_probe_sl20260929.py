"""Deep probe: (1) all live positions w/ wrong-side-SL detail, (2) loosens per day,
(3) failed modifies per day, (4) journal trail for the bad tickets."""
import os
import re
import glob
from datetime import datetime, timezone
from collections import Counter

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")

MODIFY_RE = re.compile(
    r"modify #(\d+) (buy|sell) ([\d.]+) (\w+)( sl: ([\d.]+), tp: [\d.]+)? -> sl: ([\d.]+), tp:")


def read_journal(path):
    for enc in ("utf-16", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except (UnicodeError, UnicodeDecodeError):
            continue
    return []


if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

acc = mt5.account_info()
hedged = acc.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
print(f"account {acc.login} hedging={hedged} bal={acc.balance:.2f} eq={acc.equity:.2f}")

print("\n=== live positions ===")
bad = []
for p in mt5.positions_get() or []:
    side_ok = (p.sl == 0) or (p.type == mt5.POSITION_TYPE_BUY and p.sl < p.price_current) or \
              (p.type == mt5.POSITION_TYPE_SELL and p.sl > p.price_current)
    tag = "ok " if side_ok else "BAD"
    if not side_ok:
        bad.append(p.ticket)
    print(f"[{tag}] #{p.ticket} m={p.magic} {'BUY ' if p.type == 0 else 'SELL'} vol={p.volume:.2f} "
          f"open={p.price_open} cur={p.price_current} sl={p.sl} tp={p.tp} pnl={p.profit:+.2f} "
          f"since={datetime.fromtimestamp(p.time, tz=timezone.utc):%m-%d %H:%M} cm={p.comment[:24]}")
print(f"BAD count: {len(bad)} -> {bad}")

loosen_by_day = Counter()
fails_by_day = Counter()
for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    day = os.path.basename(path)[:8]
    for ln in read_journal(path):
        if "modify #" in ln and "failed" in ln:
            fails_by_day[day] += 1
        m = MODIFY_RE.search(ln)
        if m and m.group(6):
            old, new = float(m.group(6)), float(m.group(7))
            if (m.group(2) == "buy" and new < old - 1e-9) or (m.group(2) == "sell" and new > old + 1e-9):
                loosen_by_day[day] += 1
print("\nloosened-SL modifies by day:", dict(sorted(loosen_by_day.items())))
print("failed modifies by day:", dict(sorted(fails_by_day.items())))

if bad:
    print("\n=== journal lines for BAD tickets (last 15) ===")
    hits = []
    for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
        for ln in read_journal(path):
            if any(f"#{t}" in ln for t in bad) and ("modify" in ln):
                hits.append((os.path.basename(path)[:8], ln.split("\t", 2)[-1].strip()))
    for f, ln in hits[-15:]:
        print(f"  {f} {ln[:170]}")
    if not hits:
        print("  (no modify lines found in Sep 20-29 journals)")

mt5.shutdown()
