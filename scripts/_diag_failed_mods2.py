"""For each current-era failed modify: full broker reason + position outcome
(entry/close deals, later successful mods, exit vs intended SL)."""
import os
import re
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

deals = mt5.history_deals_get(datetime(2026, 9, 20, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1))
by_pos = defaultdict(list)
for d in deals:
    if d.magic:
        by_pos[d.position_id].append(d)


def read_journal(path):
    for enc in ("utf-16", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                return f.read().splitlines()
        except (UnicodeError, UnicodeDecodeError):
            continue
    return []


failed_pos = set()
for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    for ln in read_journal(path):
        if "failed" in ln and "modify #" in ln:
            pm = re.search(r"modify #(\d+)", ln)
            if pm and int(pm.group(1)) in by_pos:
                failed_pos.add((path, ln))

print("=== failed modifies: FULL reason ===")
seen = set()
for path, ln in sorted(failed_pos):
    pm = re.search(r"modify #(\d+)", ln)
    pos = int(pm.group(1))
    tail = ln.split("tp: ")[-1]
    tail = tail.split(", ", 1)[-1] if ", " in tail else tail
    reason = tail.strip()
    print(f"  pos={pos} {os.path.basename(path)[:8]} reason={reason}")

print("\n=== outcome of each affected position ===")
mods_ok = defaultdict(list)
for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    for ln in read_journal(path):
        if "failed" in ln or "modify #" not in ln:
            continue
        pm = re.search(r"modify #(\d+) (buy|sell) [\d.]+ (\w+).*-> sl: ([\d.]+)", ln)
        if pm and int(pm.group(1)) in by_pos:
            mods_ok[int(pm.group(1))].append((ln.split("\t")[2], float(pm.group(4))))

for pos in sorted({int(re.search(r"modify #(\d+)", ln).group(1)) for _, ln in failed_pos}):
    ds = sorted(by_pos[pos], key=lambda d: d.time)
    magic = ds[0].magic
    ent = ds[0]
    out = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
    ex = out[-1] if out else None
    ok_mods = mods_ok.get(pos, [])
    exit_reason = {mt5.DEAL_REASON_SL: "SL", mt5.DEAL_REASON_TP: "TP",
                   mt5.DEAL_REASON_CLIENT: "manual/EA-close", mt5.DEAL_REASON_MOBILE: "MOBILE"}.get(
                       ex.reason if ex else None, str(ex.reason) if ex else "?")
    print(f"pos={pos} magic={magic} entry={ent.price} {datetime.fromtimestamp(ent.time, tz=timezone.utc):%H:%M} | "
          f"exit={ex.price if ex else '-'} {exit_reason} pnl={ex.profit if ex else '-':+.2f} "
          f"at {datetime.fromtimestamp(ex.time, tz=timezone.utc):%H:%M} | "
          f"ok mods after last fail: {len(ok_mods)} last={ok_mods[-1] if ok_mods else None}")
mt5.shutdown()
