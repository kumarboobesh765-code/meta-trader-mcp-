r"""One-off: diagnose the failed 16:54 MT5 launch and retry."""

import os
import re
import subprocess

TLOG = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075\logs\20260926.log")

print("=== terminal journal 16:52+ ===")
lines = []
try:
    import io
    for l in io.open(TLOG, encoding="utf-16", errors="replace").read().splitlines():
        if re.search(r"\t16:5[2-9]:", l):
            lines.append(l)
except OSError as e:
    print("read failed: %r" % e)
print("lines:", len(lines))
for l in lines[:10]:
    print("  " + l[:150])

print("=== app crash events (terminal64) last 30 min ===")
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-WinEvent -FilterHashtable @{LogName='Application';"
                    " Id=1000,1001; StartTime=(Get-Date).AddMinutes(-30)}"
                    " -ErrorAction SilentlyContinue |"
                    " ForEach-Object { $_.TimeCreated.ToString('HH:mm:ss') + ' ' +"
                    " ($_.Message -split \"`n\")[0] }"],
                   capture_output=True, text=True)
print(r.stdout.strip() or "(no crash events)")
print(r.stderr.strip()[:200])

print("=== retry launch ===")
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", r"C:\FTTest\scripts\mt_relaunch.ps1"],
                   capture_output=True, text=True, timeout=120)
print(r.stdout.strip())
print(r.stderr.strip()[:300])

import time
time.sleep(15)
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process terminal64 -ErrorAction SilentlyContinue |"
                    " ForEach-Object { \"$($_.Id) $($_.StartTime)\" }"],
                   capture_output=True, text=True)
print("=== terminal64 after retry ===")
print(r.stdout.strip() or "(still none)")
