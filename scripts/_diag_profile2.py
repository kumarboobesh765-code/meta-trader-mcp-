r"""One-off: full terminal journal context around the 15:57 chart-frame failures."""

import io
import os
import re

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
TLOG = os.path.join(TERM, "logs", "20260926.log")

lines = io.open(TLOG, encoding="utf-16", errors="replace").read().splitlines()

out = []
for l in lines:
    m = re.match(r"^[A-Z]{2}\t\d\t(\d\d):(\d\d):(\d\d)", l)
    if not m:
        continue
    hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = hh * 3600 + mm * 60 + ss
    # 15:57:15 .. 15:58:10 window
    if 15 * 3600 + 57 * 60 + 15 <= t <= 15 * 3600 + 58 * 60 + 10:
        out.append(l)

print("lines in window: %d" % len(out))
# skip the boring per-order market-closed spam
skip = ("Market closed", "buy stop", "sell stop")
for l in out:
    if not any(s in l for s in skip):
        print(l[:200])
