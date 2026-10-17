r"""One-shot Telegram ping utility for the FTTest rig. Runs ON THE VPS.

Sends a test message via the monitor's DPAPI token and prints the Telegram
API response -- a message id proves true end-to-end delivery.

Usage:  python tg_ping.py [optional text]
"""

import re
import subprocess
import sys

TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else \
        "FTTest rig: Telegram alert path OK (no action needed)."
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "(Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'}) | ConvertTo-Json"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    out = r.stdout or ""
    # parse tolerantly: PowerShell 5.1 pretty-prints the JSON and transport
    # line endings vary -- regex beats a strict json.loads here
    ok = re.search(r"[\"']ok[\"']\s*:\s*(\w+)", out)
    mid = re.search(r"[\"']message_id[\"']\s*:\s*(\d+)", out)
    if ok and ok.group(1).lower() == "true" and mid:
        print("DELIVERED message_id=%s" % mid.group(1))
        return 0
    print("NOT confirmed. stdout=%r stderr=%r" % (out[:400], r.stderr[:400]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
