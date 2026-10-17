"""Refined SL audit: split old-account vs current-rig eras.
- loosened-SL violations split by era (current = position has deals in current-account history)
- failed modifies split by era
- fixed champions = NON-T magics only (meanrev 930002, macross 930003, straddle 930004, london 930006)
  (-T twins 940002/3/4/6 are the trailing A/B variants BY DESIGN)
- trace the squeeze-EA-T mismatch position 2103798179 (failed modify?)
"""
import os
import re
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict

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

deals = mt5.history_deals_get(datetime(2026, 9, 20, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1))
pos_magic = {}
for d in deals:
    if d.magic:
        pos_magic[d.position_id] = d.magic
print(f"positions known from current-account history: {len(pos_magic)}")

loosen_cur, loosen_old = [], []
fail_cur, fail_old = 0, 0
mods_cur_by_magic = defaultdict(int)
FIXED_NON_T = {930002, 930003, 930004, 930006}
fixed_viol = []

for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    for ln in read_journal(path):
        if "modify #" not in ln:
            continue
        m = MODIFY_RE.search(ln)
        era_cur = False
        pos = None
        if "failed" in ln:
            pm = re.search(r"modify #(\d+)", ln)
            pos = int(pm.group(1)) if pm else None
            if pos in pos_magic:
                fail_cur += 1
            else:
                fail_old += 1
            continue
        if not m:
            continue
        pos = int(m.group(1))
        side, old, new = m.group(2), m.group(6), float(m.group(7))
        rec = dict(path=os.path.basename(path), t=ln.split("\t")[2] if "\t" in ln else "?",
                   pos=pos, side=side, sym=m.group(4), old=float(old) if old else None, new=new)
        if pos in pos_magic:
            era_cur = True
            mods_cur_by_magic[pos_magic[pos]] += 1
            if pos_magic[pos] in FIXED_NON_T:
                fixed_viol.append(rec)
        if old:
            old = float(old)
            loose = (side == "buy" and new < old - 1e-9) or (side == "sell" and new > old + 1e-9)
            if loose:
                (loosen_cur if era_cur else loosen_old).append(rec)

print(f"\nCURRENT-RIG loosened SLs: {len(loosen_cur)}")
for r in loosen_cur[:15]:
    print(f"  !! {r['path'][:8]} {r['t']} pos={r['pos']} {r['side']} {r['sym']} {r['old']} -> {r['new']}")
print(f"OLD-ACCOUNT-era loosened SLs (pre-rig journals, informational): {len(loosen_old)}")
mags = sorted({r['new'] - (r['old'] or r['new']) for r in loosen_old})
print(f"  magnitude range: {min(mags):.3f} .. {max(mags):.3f}")

print(f"\nFAILED modifies: current-era {fail_cur} | old-era {fail_old}")
print(f"fixed-champion (NON-T meanrev/macross/straddle/london) modifies: {len(fixed_viol)} (want 0)")
for r in fixed_viol[:10]:
    print(f"  ?? {r['path'][:8]} {r['t']} pos={r['pos']} -> {r['new']}")
print("current-era modify counts by magic:", dict(sorted(mods_cur_by_magic.items())))

print("\ntrace squeeze-EA-T pos 2103798179 (mismatch case):")
for path in sorted(glob.glob(os.path.join(LOGS, "2026092*.log"))):
    for ln in read_journal(path):
        if "2103798179" in ln and ("modify" in ln or "sl" in ln):
            print(f"  {os.path.basename(path)[:8]} {ln.split(chr(9))[2] if chr(9) in ln else '?'}  {ln.split(chr(9), 3)[-1][:130]}")
mt5.shutdown()
