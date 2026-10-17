r"""One-off final verification after the 16:35 clean MT5 restart."""

import io
import os
import re
import subprocess

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77F77C8CF37AD8BF550E51FF075")
TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
ELOG = os.path.join(TERM, "MQL5", "Logs", "20260926.log")

r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "(Get-Process terminal64 -ErrorAction SilentlyContinue).Count"],
                   capture_output=True, text=True)
print("terminal64 count:", r.stdout.strip())

r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\""
                    " | ForEach-Object { $_.CommandLine }"],
                   capture_output=True, text=True)
py = r.stdout.strip()
print("python processes:")
for line in py.splitlines():
    print("  " + line[:110])

el = io.open(ELOG, encoding="utf-16", errors="replace").read().splitlines()
after = [l for l in el if re.search(r"\t16:3[5-9]:|\t16:[4-5][0-9]:", l) and
         ("started on" in l or "initialized" in l or "FTTestMulti started" in l)]
print("EA starts after 16:35 restart: %d" % len(after))

aether = [l for l in el if "aetherflow" in l.lower() and
          re.search(r"\t16:3[5-9]:|\t16:[4-5][0-9]:", l)]
print("AetherFlow lines:")
for l in aether:
    print("  " + l[:150])

errs = [l for l in el if re.search(r"\t16:3[5-9]:|\t16:[4-5][0-9]:", l) and
        any(s in l for s in ("failed", "REFUSING", "cannot load", "not found",
                             "timeout"))]
errs = [e for e in errs if "10018" not in e and "market closed" not in e.lower()]
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
