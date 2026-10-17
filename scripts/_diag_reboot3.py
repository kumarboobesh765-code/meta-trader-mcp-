r"""One-off: final full-rig verification after the 17:01 boot."""

import io
import os
import re
import subprocess

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
ELOG = os.path.join(TERM, "MQL5", "Logs", "20260926.log")

r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "(Get-Process terminal64 -ErrorAction SilentlyContinue).Count"],
                   capture_output=True, text=True)
print("terminal64 count:", r.stdout.strip())

el = io.open(ELOG, encoding="utf-16", errors="replace").read().splitlines()
after = [l for l in el if re.search(r"\t17:0[1-9]:", l) and
         ("started on" in l or "initialized" in l or "FTTestMulti started" in l)]
print("EA starts after 17:01 boot: %d" % len(after))

kinds = {}
for l in after:
    m = re.search(r"\t([A-Za-z0-9_]+) \(", l)
    if m:
        kinds[m.group(1)] = kinds.get(m.group(1), 0) + 1
print("by EA:")
for k in sorted(kinds):
    print("  %-40s %d" % (k, kinds[k]))

aether = [l for l in el if "aetherflow" in l.lower() and "\t17:0" in l]
print("AetherFlow lines:")
for l in aether:
    print("  " + l[:150])

errs = [l for l in el if "\t17:0" in l and
        any(s in l for s in ("failed", "REFUSING", "cannot", "not found"))
        and "10018" not in l and "market closed" not in l.lower()]
print("non-10018 EA errors:", len(errs))
for l in errs[:4]:
    print("  " + l[:150])

txt = io.open(r"C:\FTTest\logs\forward_test_stdout.txt", errors="replace").read()
banners = [l for l in txt.splitlines() if "STARTED" in l]
print("runner last banner:", banners[-1] if banners else "(none)")

wd = io.open(r"C:\FTTest\logs\vps_watchdog.log", errors="replace").read().splitlines()
print("watchdog tail 2:")
for l in wd[-2:]:
    print("  " + l)
