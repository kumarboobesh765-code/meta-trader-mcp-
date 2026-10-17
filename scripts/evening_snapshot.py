"""Evening snapshot: pull live VPS state and inject into SESSION_STATE.md.

Runs on the PC (not the VPS) before the daily auto-push. READ-ONLY on the VPS:
runs perf_summary.py and greps today's EA log for equity stops.Never trades.
Snapshot lands between the EVENING_SNAPSHOT markers in SESSION_STATE.md so the
section is replaced in place on every run.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "SESSION_STATE.md"
ENV = ROOT / ".env.vps"
KEY = Path.home() / ".ssh" / "id_ed25519_vps"

BEGIN = "<!-- EVENING_SNAPSHOT:BEGIN (auto-updated daily 20:00 by scripts/evening_snapshot.py) -->"
END = "<!-- EVENING_SNAPSHOT:END -->"


def load_env(path):
    vals = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def ssh(host, user, cmd):
    r = subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "BatchMode=yes", f"{user}@{host}", cmd],
        capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr)


def main():
    env = load_env(ENV)
    host = env.get("VPS_HOST") or env.get("HOST")
    user = env.get("VPS_USER") or env.get("USER")
    if not host or not user:
        sys.exit("evening_snapshot: cannot read VPS host/user from .env.vps")

    rc1, perf = ssh(host, user, "python C:\\FTTest\\perf_summary.py")
    rc2, ops = ssh(host, user, (
        'powershell -NoProfile -Command "'
        'Get-Process terminal64 -ErrorAction SilentlyContinue | Select Id,StartTime | Format-Table -HideTableHeaders; '
        '$b=\\"C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\D0E8209F77C8CF37AD8BF550E51FF075\\"; '
        '$d=(Get-Date).ToString(\\"yyyyMMdd\\"); '
        '$p=\\"$b\\MQL5\\Logs\\$d.log\\"; '
        'if(Test-Path $p){ Select-String -Path $p -Pattern (\\"EQUITY STOP\\",\\"pause lifted\\") | '
        'Select -Last 6 | ForEach-Object { $_.Line } } else { Write-Output \\"(no EA log today - weekend or terminal down)\\" }"'))

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    text = STATE.read_text(encoding="utf-8")
    block = (f"{BEGIN}\n\n"
             f"### Evening snapshot — auto-generated {now}\n\n"
             f"**Source:** live pull from the VPS by `scripts/evening_snapshot.py` (perf_summary.py + today's EA log).\n\n"
             f"```text\n{perf.strip()}\n```\n\n"
             f"```text\n{ops.strip()}\n```\n\n"
             f"{END}\n")

    if BEGIN in text and END in text:
        pre = text.split(BEGIN, 1)[0]
        post = text.split(END, 1)[1]
        new = pre + block + post
    else:
        # no markers yet: append after the "last updated" line
        new = text.replace(
            "# SESSION_STATE.md — live handoff",
            block + "\n# SESSION_STATE.md — live handoff", 1)

    if new == text:
        print("no change")
        return

    STATE.write_text(new, encoding="utf-8")
    print(f"snapshot written ({rc1=},{rc2=}) -- {len(new)} chars")


if __name__ == "__main__":
    main()
