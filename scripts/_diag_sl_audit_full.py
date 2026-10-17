"""Full SL-behavior audit (current account, since start).
A) Terminal journals (Sep 26 -> today): every position SL modify
   - loosen detection (buy: new<old, sell: new>old = violation)
   - fixed-champion families must have ZERO position-SL modifies
   - failed modify count
B) MT5 deal history: SL-hit exits vs last journaled SL (reconciliation)
C) Live: open positions SL sanity
Usage: python _diag_sl_audit_full.py
"""
import os
import re
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")

FIXED_MAGICS = {930002, 940002, 930003, 940003, 930004, 940004, 930006, 940006}
TRAIL_MAGICS = {930001, 940001, 930005, 940005, 930007, 940007, 930008, 940008,
                930009, 940009, 930010, 940010, 930011, 940011,
                950001, 960001, 950002, 960002}

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
print(f"account {acc.login} ({acc.server}) balance={acc.balance:.2f} equity={acc.equity:.2f}")

# position_id -> (magic, symbol) from full deal history
pos_magic = {}
deals = mt5.history_deals_get(datetime(2026, 9, 20, tzinfo=timezone.utc),
                              datetime.now(timezone.utc) + timedelta(days=1))
for d in deals:
    if d.magic:
        pos_magic[d.position_id] = (d.magic, d.symbol)

# ---------- A) journal modify scan ----------
mods = []          # (file, time, pos, side, sym, old, new)
fails = 0
pending_mods = 0
files = sorted(glob.glob(os.path.join(LOGS, "2026092*.log")))
for path in files:
    day = os.path.basename(path)[:8]
    for ln in read_journal(path):
        if "modify #" not in ln:
            continue
        if "failed" in ln:
            fails += 1
            continue
        m = MODIFY_RE.search(ln)
        if not m:
            if " stop " in ln or " limit " in ln:
                pending_mods += 1
            continue
        t = ln.split("\t")[2] if "\t" in ln else "??:??"
        pos = int(m.group(1))
        mods.append(dict(day=day, t=t, pos=pos, side=m.group(2), sym=m.group(4),
                         old=float(m.group(6)) if m.group(6) else None,
                         new=float(m.group(7))))

print(f"\njournal files scanned: {len(files)} ({os.path.basename(files[0])} .. {os.path.basename(files[-1])})" if files else "no journals")
print(f"position-SL modify requests: {len(mods)} | pending-order modifies (session refresh): {pending_mods} | FAILED modifies: {fails}")

loosens = []
by_fam = defaultdict(int)
fixed_violations = []
last_sl = {}
for m in mods:
    fam_magic = pos_magic.get(m["pos"], (0, ""))[0]
    if fam_magic in FIXED_MAGICS:
        fixed_violations.append(m)
    by_fam[pos_magic.get(m["pos"], (0, ""))[0] or "manual/0"] += 1
    if m["old"] is not None:
        if m["side"] == "buy" and m["new"] < m["old"] - 1e-9:
            loosens.append(m)
        if m["side"] == "sell" and m["new"] > m["old"] + 1e-9:
            loosens.append(m)
    last_sl[m["pos"]] = m["new"]

print(f"LOOSENED-SL violations: {len(loosens)}")
for m in loosens[:10]:
    print(f"  !! {m['day']} {m['t']} pos={m['pos']} {m['side']} {m['sym']} {m['old']} -> {m['new']}")
print(f"fixed-champion (meanrev/macross/straddle/london) position-SL modifies: {len(fixed_violations)} (want 0)")
for m in fixed_violations[:10]:
    print(f"  ?? {m['day']} {m['t']} pos={m['pos']} {m['side']} {m['sym']} -> {m['new']}")
print("modify counts by magic:", dict(sorted(by_fam.items(), key=lambda kv: str(kv[0]))))

# ---------- B) SL-exit reconciliation ----------
print("\nSL-hit exits vs last journaled SL:")
sl_exits = defaultdict(list)
for d in deals:
    if d.entry == mt5.DEAL_ENTRY_OUT and getattr(d, "reason", None) == mt5.DEAL_REASON_SL:
        sl_exits[pos_magic.get(d.position_id, (0, d.symbol))].append(d)
total, matched, nojournal = 0, 0, 0
for (magic, sym), ds in sorted(sl_exits.items()):
    for d in ds:
        total += 1
        ls = last_sl.get(d.position_id)
        if ls is None:
            nojournal += 1
            continue
        tol = 1.5 if "XAU" in sym else 0.0015
        if abs(abs(d.price - ls)) <= tol:
            matched += 1
        else:
            print(f"  ?? pos={d.position_id} {sym} closed {d.price} but last journaled sl={ls} (magic {magic})")
print(f"  SL exits: {total} | match last trailed SL: {matched} | no journal modify (SL set at entry): {nojournal}")

# ---------- C) live sanity ----------
print("\nopen positions SL sanity:")
bad = 0
for p in (mt5.positions_get() or []):
    ok_side = (p.sl == 0) or (p.type == mt5.POSITION_TYPE_BUY and p.sl < p.price_current) or \
              (p.type == mt5.POSITION_TYPE_SELL and p.sl > p.price_current)
    flag = "OK" if ok_side else "BAD"
    if not ok_side:
        bad += 1
    print(f"  [{flag}] {p.ticket} sl-side ok={ok_side} sl={p.sl} price={p.price_current}")
print(f"BAD live SLs: {bad}")
mt5.shutdown()
print("\nVERDICT:", "CLEAN" if (not loosens and not fixed_violations and not bad and fails == 0) else "REVIEW NEEDED")
