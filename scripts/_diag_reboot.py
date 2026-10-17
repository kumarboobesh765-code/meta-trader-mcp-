r"""One-off post-reboot verification for the AetherFlow rollout."""

import io
import os
import re
import subprocess

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
TLOG = os.path.join(TERM, "logs", "20260926.log")
ELOG = os.path.join(TERM, "MQL5", "Logs", "20260926.log")

print("=== python processes ===")
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\""
                    " | ForEach-Object { \"$($_.ProcessId) :: $_.CommandLine\" }"],
                   capture_output=True, text=True)
print(r.stdout.strip() or "(none)")

print("=== terminal64 processes ===")
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process terminal64 -ErrorAction SilentlyContinue"
                    " | ForEach-Object { \"$($_.Id) $($_.StartTime)\" }"],
                   capture_output=True, text=True)
print(r.stdout.strip() or "(none)")

tl = io.open(TLOG, encoding="utf-16", errors="replace").read().splitlines()
after_boot = [l for l in tl if re.search(r"\t16:1[0-9]:|\t16:2[0-9]:", l)]

print("=== login/sync after reboot ===")
for l in after_boot:
    if "authorized" in l or "terminal synchronized" in l or "started for MetaQuotes" in l:
        print("  " + l[:170])

el = io.open(ELOG, encoding="utf-16", errors="replace").read().splitlines()
starts = [l for l in el if "started on" in l or "initialized" in l
          or "started:" in l]
after = [l for l in el if re.search(r"\t16:1[0-9]:", l) and
         ("started on" in l or "initialized" in l or "FTTestMulti started" in l)]
print("=== EA starts after reboot: %d ===" % len(after))
aether = [l for l in el if "aetherflow" in l.lower() and re.search(r"\t16:", l)]
print("=== AetherFlow lines after reboot ===")
for l in aether:
    print("  " + l[:170])

print("=== EA init errors after reboot ===")
errs = [l for l in el if re.search(r"\t16:1[0-9]:", l) and
        any(s in l for s in ("failed", "REFUSING", "cannot", "not found"))]
for l in errs[:6]:
    print("  " + l[:170])
print("error count:", len(errs))

print("=== runner stdout: STARTED banners (last 2) ===")
txt = io.open(r"C:\FTTest\logs\forward_test_stdout.txt", errors="replace").read()
banners = [l for l in txt.splitlines() if "STARTED" in l]
for l in banners[-2:]:
    print("  " + l)
print("=== runner stdout tail 3 ===")
for l in txt.splitlines()[-3:]:
    print("  " + l)

print("=== watchdog tail 4 ===")
for l in io.open(r"C:\FTTest\logs\vps_watchdog.log",
                 errors="replace").read().splitlines()[-4:]:
    print("  " + l)
