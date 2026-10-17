r"""One-off: why does MTRelaunch fire but not spawn terminal64?"""

import subprocess
import time


def ps(cmd, timeout=60):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.stderr.strip()


print("=== sessions (qwinsta) ===")
out, _ = ps("qwinsta")
print(out)

print("=== short path exists? ===")
out, err = ps("Test-Path 'C:\\PROGRA~1\\METATR~1\\TERMIN~1.EXE'; "
              "Test-Path 'C:\\Program Files\\MetaTrader 5\\terminal64.exe'")
print(out or err)

print("=== create + run task, query state before delete ===")
out, err = ps("schtasks /Create /TN MTRelaunchDiag "
              "/TR 'C:\\PROGRA~1\\METATR~1\\TERMIN~1.EXE /config:C:\\FTTest\\mt5_autologin.ini' "
              "/SC ONCE /ST 23:59 /F")
print(out or err)
out, err = ps("schtasks /Run /TN MTRelaunchDiag")
print(out or err)
for i in range(6):
    time.sleep(5)
    out, _ = ps("(Get-Process terminal64 -ErrorAction SilentlyContinue)"
                " | ForEach-Object { \"$($_.Id) $($_.StartTime)\" }")
    print("t+%ds terminal64: %s" % ((i + 1) * 5, out or "(none)"))
    if out:
        break

print("=== task last result ===")
out, _ = ps("schtasks /Query /TN MTRelaunchDiag /V /FO LIST |"
            " Select-String 'Result','Status','Logon Mode','Run As'")
print(out)

print("=== cleanup ===")
out, _ = ps("schtasks /Delete /TN MTRelaunchDiag /F")
print(out)
