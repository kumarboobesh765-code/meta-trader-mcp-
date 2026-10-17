"""List current-era FAILED modify attempts with broker reason, to classify as benign races or real defects."""
import os
import re
import glob
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

deals = mt5.history_deals_get(datetime(2026, 9, 20, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1))
pos_magic = {}
closed_at = {}
for d in deals:
    if d.magic:
        pos_magic[d.position_id] = d.magic
    if d.entry == mt5.DEAL_ENTRY_OUT:
        closed_at[d.position_id] = d.time


def read_journal(path):
    for enc in ("utf-16", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except (UnicodeError, UnicodeDecodeError):
            continue
    return []


print("current-era FAILED modify lines (position exists in current-account history):")
n = 0
race = 0
for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    for ln in read_journal(path):
        if "failed" not in ln or "modify #" not in ln:
            continue
        pm = re.search(r"modify #(\d+)", ln)
        if not pm:
            continue
        pos = int(pm.group(1))
        if pos not in pos_magic:
            continue
        n += 1
        reason = ln.split("\t")[-1].strip()[:110]
        cls = "?"
        if pos in closed_at:
            cls = "RACE? (position has a close deal)"
        print(f"  {os.path.basename(path)[:8]} {ln.split(chr(9))[2]} pos={pos} magic={pos_magic[pos]} -> {reason}  [{cls}]")
print(f"total current-era failed modifies: {n}")
mt5.shutdown()
