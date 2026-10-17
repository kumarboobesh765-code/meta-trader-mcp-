r"""Low-noise VPS watchdog for the FTTest rig. Runs ON THE VPS, forever.

Replaces the chatty monitor.ps1 loop with a Telegram-only watchdog that
honors "do not send alerts frequently":

1. UNREACHABLE >= 5 minutes  -- a real outage (frozen console, dead MT5,
   hung internet, stuck account session) is confirmed on 5 consecutive
   60-second probes and reported once, then suppressed until fully
   recovered, which is reported once. A single bad probe never alerts.
   While still down, a "STILL down" reminder repeats every ~30 minutes.
2. FIRST FTTEST FILL  -- when the first position with one of our magics
   opens on Vantage, ping once ("the rig is actually trading"), then never
   again (marker file).
3. FIRST AETHERFLOW-M15 TRADE -- when 950001 (M15 confluence, fixed twin)
   first opens, post entry/SL/TP from its journal OPEN line plus the
   trailing twin 960001's fill from deals.csv, once (marker file).

Everything is decided by PROBES the script itself makes -- an SSH drop on
your side cannot trigger anything. The MT5 probe opens a real terminal IPC
connection each cycle (cheap, catches wedged terminals a process list misses).

Telegram: reuses the DPAPI-encrypted bot token from the VPS monitor.

Scheduled task: setup_vps_watchdog.ps1 (hidden, no time limit, restart on
crash, starts at boot/logon). Single instance via named mutex.
"""

import ctypes
import csv
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
LOG = r"C:\FTTest\logs\vps_watchdog.log"
MARKER = r"C:\FTTest\logs\watchdog_first_fill.sent"
STATE = r"C:\FTTest\logs\vps_watchdog_state.txt"
RUNNER_STDOUT = r"C:\FTTest\logs\forward_test_stdout.txt"

# First aetherflow-M15 trade alert: fires once when 950001 (M15 confluence,
# fixed twin) first opens a position, then never again (marker file).
AETHER_M15_MAGIC = 950001
AETHER_M15_MARKER = r"C:\FTTest\logs\watchdog_aether_m15.sent"
AETHER_DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
               r"\D0E8209F77C8CF37AD8BF550E51FF075")
DEALS_CSV = r"C:\FTTest\logs\forward\deals.csv"

DOWN_CONFIRM_CYCLES = 5   # 5 probes x 60s = 5 minutes of continuous failure
REALERT_EVERY_CYCLES = 30 # while still down, re-alert every 30 cycles (~30 min)
CYCLE_SEC = 60
RUNNER_STALE_SEC = 600    # runner writes every ~30-60s while IPC is alive


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(datetime.now().isoformat() + " " + msg + "\n")
    except OSError:
        pass


def send_telegram(text):
    try:
        ps = ("$t=(Get-Content '%s' -Raw).Trim();"
              "$s=ConvertTo-SecureString $t;"
              "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
              "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
              "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
              " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
              % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
        log("telegram sent: %s" % text)
    except Exception as e:
        log("telegram send failed: %r" % e)


def probe_internet():
    """One ICMP probe; retry once so a single lost packet is not a failure."""
    r = subprocess.run(["ping", "-n", "1", "-w", "4000", "1.1.1.1"],
                       capture_output=True, text=True, errors="replace")
    if r.returncode == 0:
        return True
    r = subprocess.run(["ping", "-n", "1", "-w", "4000", "8.8.8.8"],
                       capture_output=True, text=True, errors="replace")
    return r.returncode == 0


def probe_mt5():
    """PASSIVE terminal-health check -- deliberately NO mt5.initialize() here:
    the MetaTrader5 python module SPAWNS a new terminal64 when it cannot
    attach, which multiplied zombie terminals on this 1 GB box.

    Healthy = terminal64 process running AND the python runner's stdout is
    fresh (the runner writes every ~30-60s whenever its MT5 IPC works; a
    wedged/logged-out terminal stalls that log within a couple of minutes).
    """
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                             capture_output=True, text=True,
                             errors="replace").stdout.lower()
        if "terminal64.exe" not in out:
            return False
    except Exception:
        return False
    try:
        age = time.time() - os.path.getmtime(RUNNER_STDOUT)
        return age <= RUNNER_STALE_SEC
    except OSError:
        return False


def read_int(path, default=0):
    try:
        return int(open(path).read().strip() or default)
    except (OSError, ValueError):
        return default


def load_state():
    st = {"down": 0, "down_notified": 0, "down_reason": "", "down_alert_at": 0}
    try:
        for line in open(STATE):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k in st:
                    st[k] = v if k == "down_reason" else int(v)
    except OSError:
        pass
    return st


def save_state(st):
    try:
        with open(STATE, "w") as f:
            f.write("down=%d\ndown_notified=%d\ndown_reason=%s\n"
                    "down_alert_at=%d\n"
                    % (st["down"], st["down_notified"], st["down_reason"],
                       st["down_alert_at"]))
    except OSError:
        pass


def first_fill_check():
    """One-time alert when the first FTTest-magic position opens. Uses the
    runner's own deals.csv (passive) instead of an MT5 IPC probe -- see
    probe_mt5() for why this watchdog must never attach to the terminal."""
    if os.path.exists(MARKER):
        return
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from forward_test import MAGICS
        our = set(MAGICS)
        deals_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs", "forward", "deals.csv")
        if not os.path.exists(deals_path):
            return
        import csv
        with open(deals_path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    magic = int(row.get("magic", "0"))
                except ValueError:
                    continue
                if magic in our and row.get("entry") == "in":
                    open(MARKER, "w").write(datetime.now().isoformat())
                    send_telegram(
                        "FTTest: first position OPEN on Vantage! %s %s %s "
                        "@ %s (magic %d). The rig is trading."
                        % (row.get("symbol"), row.get("type"),
                           row.get("volume"), row.get("price"), magic))
                    return
    except Exception as e:
        log("first_fill_check error: %r" % e)


def read_open_journal(days=7):
    """Latest '<Label> OPEN BUY|SELL ... @ price sl=X tp=Y ok=' journal line
    per aether magic from the MT5 terminal/Experts journals (UTF-16).
    Returns {magic: {'time': datetime|None, 'text': str}}."""
    best = {}
    now = time.time()
    journals = (glob.glob(os.path.join(AETHER_DATA, "logs", "*.log"))
                + glob.glob(os.path.join(AETHER_DATA, "MQL5", "Logs", "*.log")))
    for j in journals:
        if now - os.path.getmtime(j) > days * 86400:
            continue
        try:
            txt = open(j, "rb").read().decode("utf-16", errors="replace")
        except OSError:
            continue
        for line in txt.splitlines():
            if " OPEN " not in line or "ok=true" not in line:
                continue
            mm = re.search(r"\b(950001|960001|950002|960002)\b", line)
            if not mm:
                continue
            m = int(mm.group(1))
            prev = best.get(m)
            if prev is None or line > prev["text"]:  # ISO-ish stamps sort lexically
                best[m] = {"text": line.strip(), "file": os.path.basename(j)}
    return best


def aether_m15_check():
    """One-time alert when the first aetherflow-M15 confluence trade opens.
    950001 (fixed twin) opening is the trigger; the trailing twin 960001 is
    detected from deals.csv (same entry) and its detail is appended. Fully
    passive: journals + deals.csv only -- never attaches to the terminal."""
    if os.path.exists(AETHER_M15_MARKER):
        return
    try:
        jrn = read_open_journal(7)
        base = jrn.get(AETHER_M15_MAGIC)
        if not base or " OPEN " not in base["text"]:
            return
        # entry/SL/TP are in the EA's own OPEN line:
        # '[AF 950001] OPEN BUY 0.1 @ 4268.52 sl=4275.1 tp=4240.3 ok=true ret=10009'
        mm = re.search(r"OPEN (BUY|SELL)\s+([\d.]+) @ ([\d.]+) sl=([\d.]+) tp=([\d.]+)",
                       base["text"])
        if not mm:
            log("aether open line lacks sl/tp, raw: %s" % base["text"])
            return
        side, vol, entry, sl, tp = mm.groups()

        twin_txt = "twin 960001: not seen in deals.csv yet (logs within ~1 min)"
        try:
            with open(DEALS_CSV, newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("magic") == str(960001) and row.get("entry") == "in":
                        twin_txt = ("twin 960001: %s %s @ %s (pos #%s)"
                                    % (row.get("type"), row.get("volume"),
                                       row.get("price"), row.get("position_id")))
                        break  # first (= earliest) twin fill
        except OSError:
            pass

        open(AETHER_M15_MARKER, "w").write(datetime.now().isoformat())
        send_telegram(
            "AetherFlow M15: FIRST CONFLUENCE TRADE!\n  fixed 950001: %s %s "
            "lots @ %s sl=%s tp=%s\n  %s\n(journal: %s)"
            % (side, vol, entry, sl, tp, twin_txt, base["file"]))
        log("aether m15 first-trade alert sent (marker written)")
    except Exception as e:
        log("aether_m15_check error: %r" % e)


def main():
    k32 = ctypes.windll.kernel32
    h = k32.CreateMutexW(None, False, "Global\\VPSWatchdogMutex")
    if h == 0 or k32.GetLastError() == 183:
        log("another watchdog instance is running; exiting.")
        return 1

    log("vps watchdog started (probe every %ds, alert after %d consecutive "
        "failed cycles)" % (CYCLE_SEC, DOWN_CONFIRM_CYCLES))
    st = load_state()
    mt5_ok_at_start = probe_mt5()
    log("initial probe: mt5=%s" % mt5_ok_at_start)

    while True:
        net = probe_internet()
        mt5 = probe_mt5() if net else False  # MT5 probe is meaningless without net
        ok = net and mt5

        if ok:
            if st["down_notified"]:
                send_telegram("VPS watchdog: recovered. Internet and MT5 "
                              "respond again (down for ~%d min)."
                              % (st["down"] * CYCLE_SEC // 60))
            st["down"] = 0
            st["down_notified"] = 0
            st["down_reason"] = ""
            st["down_alert_at"] = 0
        else:
            reason = "internet" if not net else "MT5 terminal"
            st["down"] += 1
            if st["down"] >= DOWN_CONFIRM_CYCLES and not st["down_notified"]:
                st["down_notified"] = 1
                st["down_reason"] = reason
                send_telegram(
                    "VPS watchdog: UNREACHABLE >= %d minutes (%s not "
                    "responding). SSH console session may be wedged; reboot "
                    "if tscon/relaunch does not fix it."
                    % (st["down"] * CYCLE_SEC // 60, reason))
            elif st["down"] >= DOWN_CONFIRM_CYCLES:
                st["down_reason"] = st["down_reason"] or reason
                if (st["down"] - st["down_alert_at"]) >= REALERT_EVERY_CYCLES:
                    st["down_alert_at"] = st["down"]
                    send_telegram(
                        "VPS watchdog: STILL down after ~%d minutes (%s not "
                        "responding). Consider a reboot: shutdown /r /t 5"
                        % (st["down"] * CYCLE_SEC // 60, st["down_reason"]))
        save_state(st)

        if ok:
            first_fill_check()
            aether_m15_check()

        log("net=%s mt5=%s down_streak=%d notified=%s"
            % (net, mt5, st["down"], bool(st["down_notified"])))
        time.sleep(CYCLE_SEC)


if __name__ == "__main__":
    sys.exit(main())
