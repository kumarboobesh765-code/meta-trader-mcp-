"""Follow-up: (1) did the 4 crossed-SL sells close? (2) today's exits grouped by close
reason, (3) slippage case pos 2103798179 deal+journal detail, (4) last 3h SL exits detail."""
import os
import re
import glob
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import MetaTrader5 as mt5

DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
LOGS = os.path.join(DATA, "logs")
UTC = timezone.utc
MAGICS = {930001: "breakout-A", 940001: "breakout-B", 930002: "meanrev-A", 940002: "meanrev-B",
          930003: "macross-A", 940003: "macross-B", 930004: "straddle-A", 940004: "straddle-B",
          930005: "orderflow-A", 940005: "orderflow-B", 930006: "london-A", 940006: "london-B",
          930007: "squeeze-A", 940007: "squeeze-B", 930008: "profile-A", 940008: "profile-B",
          930009: "scalp-A", 940009: "scalp-B", 930010: "trendpull-A", 940010: "trendpull-B",
          930011: "donchian-A", 940011: "donchian-B", 930012: "trend-A", 940012: "trend-B",
          930013: "supres-A", 940013: "supres-B", 950001: "aether-M5", 960001: "aether-T",
          950002: "aether2-M5", 960002: "aether2-T", 950003: "aetherH4-U", 960003: "aetherH4-T",
          26092501: "legacy-probe"}

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

now = datetime.now(UTC)
print(f"=== now {now:%m-%d %H:%M:%S} UTC ===")

print("\n=== the 4 crossed-SL sells now ===")
open_now = mt5.positions_get() or []
open_ids = {p.ticket for p in open_now}
for t in (2103956425, 2103956435, 2104175793, 2107181617):
    if t in open_ids:
        p = next(x for x in open_now if x.ticket == t)
        print(f"  STILL OPEN #{t} sl={p.sl} cur={p.price_current} pnl={p.profit:+.2f}")
    else:
        print(f"  gone (closed) #{t}")

print("\n=== today's closed trades by reason (UTC day) ===")
d0 = datetime(now.year, now.month, now.day, tzinfo=UTC)
deals = mt5.history_deals_get(d0, now + timedelta(hours=1)) or []
pos_magic = {}
all_deals = mt5.history_deals_get(d0 - timedelta(days=2), now + timedelta(hours=1)) or []
for d in all_deals:
    if d.magic:
        pos_magic[d.position_id] = d.magic
reasons = {mt5.DEAL_REASON_SL: "SL", mt5.DEAL_REASON_TP: "TP", mt5.DEAL_REASON_CLIENT: "EA/manual",
           mt5.DEAL_REASON_MOBILE: "MOBILE", mt5.DEAL_REASON_SO: "STOPOUT"}
cnt, pnl = Counter(), Counter()
detail = defaultdict(list)
for d in deals:
    if d.entry != mt5.DEAL_ENTRY_OUT:
        continue
    r = reasons.get(d.reason, str(d.reason))
    m = pos_magic.get(d.position_id, 0)
    cnt[(r, MAGICS.get(m, str(m)))] += 1
    pnl[(r, MAGICS.get(m, str(m)))] += d.profit
    detail[d.position_id].append(d)
print(f"{'reason/family':28s} {'n':>4s} {'pnl':>10s}")
for k in sorted(cnt, key=lambda k: -pnl[k]):
    print(f"{k[0]+'/'+k[1]:28s} {cnt[k]:4d} {pnl[k]:+10.2f}")
tot_n, tot_p = sum(cnt.values()), sum(pnl.values())
print(f"{'TOTAL today':28s} {tot_n:4d} {tot_p:+10.2f}")

print("\n=== SL exits last 3h (slippage check) ===")
for pid, ds in sorted(detail.items()):
    for d in ds:
        if d.reason == mt5.DEAL_REASON_SL and (now - datetime.fromtimestamp(d.time, UTC)) < timedelta(hours=3):
            m = pos_magic.get(pid, 0)
            print(f"  #{pid} {MAGICS.get(m, m)} price={d.price} "
                  f"pnl={d.profit:+.2f} at {datetime.fromtimestamp(d.time, UTC):%H:%M:%S}")

print("\n=== slippage case #2103798179 ===")
ds = [d for d in all_deals if d.position_id == 2103798179]
for d in sorted(ds, key=lambda x: x.time):
    print(f"  {datetime.fromtimestamp(d.time, UTC):%m-%d %H:%M:%S} entry={d.entry} price={d.price} "
          f"pnl={d.profit:+.2f} reason={reasons.get(d.reason, d.reason)}")
for path in sorted(glob.glob(os.path.join(LOGS, "20260928*.log"), )) + sorted(glob.glob(os.path.join(LOGS, "20260929*.log"))):
    for enc in ("utf-16", "cp1252"):
        try:
            lines = open(path, encoding=enc).read().splitlines()
            break
        except (UnicodeError, UnicodeDecodeError):
            lines = []
    hits = [ln.split("\t", 2)[-1].strip() for ln in lines if "#2103798179" in ln]
    for h in hits[-6:]:
        print(f"  [{os.path.basename(path)[:8]}] {h[:160]}")
mt5.shutdown()
