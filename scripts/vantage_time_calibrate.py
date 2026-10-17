r"""Calibrate SERVER_TIME_OFFSET + London hours for Vantage. Runs ON THE VPS.

How it decides (designed around the Saturday trap -- do NOT "measure" from
stale weekend bars: bar staleness looks like a 19h timezone shift):

1. SERVER_TIME_OFFSET: only when a market is LIVE. Probes ticks on XAUUSD +
   the 4 FX pairs; a symbol is live if its newest tick is <= 120s old.
   offset = median(tick.time) - local_now, rounded to whole hours
   (MT5 stamps ticks in broker-server epoch). No live ticks (weekend /
   before Monday's gold open) -> offset UNKNOWN -> nothing is patched.
2. LONDON hours: derived from the measured offset, not from "activity
   peaks" (max-activity hours detect the NY-open impulse, not London).
   London opens 08:00 Europe/London (07:00 UTC during BST). In server time:
     start = (7 if BST else 8) + offset_hours,  end = start + 6
   The per-hour range*volume activity profile is still computed and logged
   as a cross-check only.
3. Drift guardrail: refuses to move London hours or offset by more than 3h
   unless --force is given.

Patch targets (single-source constants mirrored across the rig):
  - scripts/forward_test.py : LONDON_START_HOUR / LONDON_END_HOUR /
                              SERVER_TIME_OFFSET
  - MQL5\\Experts\\FTTest\\FTTestCore.mqh, FTTestEA.mq5, FTTestMultiEA.mq5:
      the two LONDON defines (EA uses server-clock hours directly)

If anything changed: recompiles all FTTest*.mq5, restarts the runner and
MT5 (EAs then load fresh ex5 files). Telegram ping only on patch/failure.

Schedule (MON 10:05 server = shortly after gold opens, so ticks are live;
restarts are tolerated by the rig and only ever happen when values drifted):
  schtasks /TN FTTimeCal /TR "<python> C:\FTTest\scripts\vantage_time_calibrate.py --apply"
    /SC WEEKLY /D MON /ST 10:05
"""

import os
import re
import statistics
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

LOG = r"C:\FTTest\logs\vantage_time_calibrate.log"
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
RUNNER = r"C:\FTTest\scripts\forward_test.py"
EA_DIR = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
          r"\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest")
RESTART_RUNNER = r"C:\FTTest\scripts\restart_runner.bat"
COMPILE_BAT = r"C:\FTTest\scripts\compile_ea_vps.bat"
RELAUNCH_PS = r"C:\FTTest\scripts\mt_relaunch.ps1"

TICK_LIVE_SEC = 120      # a tick this fresh = market open for that symbol
MAX_DRIFT_HOURS = 3      # refuse to jump more than this without --force


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
    except Exception as e:
        log("telegram send failed: %r" % e)


def uk_bst_active(year, month, day):
    """Europe/London DST (BST): last Sunday of March -> last Sunday of Oct."""
    import calendar

    def last_sunday(y, m):
        last = calendar.monthrange(y, m)[1]
        wd = calendar.weekday(y, m, last)  # Mon=0..Sun=6
        return last - ((wd + 1) % 7)       # back to Sunday

    if 3 < month < 10:
        return True
    if month == 3:
        return day >= last_sunday(year, 3)
    if month == 10:
        return day < last_sunday(year, 10)
    return False


def measure_offset_hours():
    """Server-UTC offset in whole hours from LIVE ticks, or None if the
    market is closed. Median across live symbols, rounded to whole hours
    (offsets are always whole hours in practice)."""
    syms = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    now = datetime.now().timestamp()
    deltas = []
    for s in syms:
        t = mt5.symbol_info_tick(s)
        if t is None or not t.time:
            continue
        age = now - t.time          # positive: server stamp behind local now
        if abs(age) <= TICK_LIVE_SEC:
            deltas.append(t.time - now)
    if not deltas:
        return None
    return int(round(statistics.median(deltas) / 3600.0))


def activity_peaks_info(days=20):
    """Cross-check info: top-activity server hours per day (range*volume).
    NOT used for decisions -- these cluster on the NY-open impulse."""
    try:
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 1, days * 96 + 96)
        if rates is None or len(rates) < 500:
            return None
        bars = [{"time": int(r["time"]), "high": r["high"], "low": r["low"],
                 "vol": r["tick_volume"] or 0} for r in rates]
        dayd = sorted({b["time"] // 86400 for b in bars})[-days:]
        peaks = []
        for d in dayd:
            per_hour, tot = {}, 0.0
            for b in bars:
                if not (d * 86400 <= b["time"] < (d + 1) * 86400):
                    continue
                h = (b["time"] % 86400) // 3600
                rng, vol = per_hour.get(h, (0.0, 0.0))
                per_hour[h] = (max(rng, b["high"] - b["low"]), vol + b["vol"])
                tot += b["vol"]
            if tot <= 0 or len(per_hour) < 12:
                continue  # holiday / half day
            best = max(per_hour.items(), key=lambda kv: kv[1][0] * kv[1][1])
            peaks.append(best[0])
        return peaks
    except Exception:
        return None


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def patch(text, replacements):
    changed = False
    for pat, repl in replacements:
        new = re.sub(pat, repl, text)
        if new != text:
            changed = True
            text = new
    return text, changed


def apply_patch(new_start, new_end, new_off):
    changed_files = []

    src = read(RUNNER)
    src2, ch = patch(src, [
        (r"(?m)^LONDON_START_HOUR\s*=\s*\d+", "LONDON_START_HOUR = %d" % new_start),
        (r"(?m)^LONDON_END_HOUR\s*=\s*\d+", "LONDON_END_HOUR = %d" % new_end),
        (r"(?m)^SERVER_TIME_OFFSET\s*=\s*\d+", "SERVER_TIME_OFFSET = %d" % new_off),
    ])
    if ch:
        write(RUNNER, src2)
        changed_files.append("forward_test.py")

    for fname in ("FTTestCore.mqh", "FTTestEA.mq5", "FTTestMultiEA.mq5"):
        p = os.path.join(EA_DIR, fname)
        if not os.path.exists(p):
            log("skip missing %s" % p)
            continue
        src = read(p)
        src2, ch = patch(src, [
            (r"(?m)^#define\s+LONDON_START_HOUR\s+\d+",
             "#define LONDON_START_HOUR %d" % new_start),
            (r"(?m)^#define\s+LONDON_END_HOUR\s+\d+",
             "#define LONDON_END_HOUR %d" % new_end),
        ])
        if ch:
            write(p, src2)
            changed_files.append(fname)
    return changed_files


def current_values():
    src = read(RUNNER)
    return (int(re.search(r"(?m)^LONDON_START_HOUR\s*=\s*(\d+)", src).group(1)),
            int(re.search(r"(?m)^LONDON_END_HOUR\s*=\s*(\d+)", src).group(1)),
            int(re.search(r"(?m)^SERVER_TIME_OFFSET\s*=\s*(\d+)", src).group(1)))


def main():
    apply = "--apply" in sys.argv
    force = "--force" in sys.argv
    if not mt5.initialize():
        log("mt5.initialize failed: %s" % (mt5.last_error(),))
        send_telegram("FTTimeCal: mt5 init FAILED")
        return 1

    try:
        off_h = measure_offset_hours()
        peaks = activity_peaks_info()
    finally:
        mt5.shutdown()

    now = datetime.now()
    bst = uk_bst_active(now.year, now.month, now.day)
    if off_h is None:
        log("market CLOSED (no live ticks) -> offset not measurable, "
            "patch skipped. Rerun after Monday's gold open (task: Mon 10:05).")
        return 0

    london_start = (7 if bst else 8) + off_h
    london_end = london_start + 6
    new_off = off_h * 3600
    log("measured: offset=UTC%+d (live ticks), BST=%s -> London window "
        "%02d-%02dh; activity peaks (info): %s"
        % (off_h, bst, london_start, london_end, peaks))

    cur_start, cur_end, cur_off = current_values()
    log("current:  start=%d end=%d offset=%d (UTC%+d)"
        % (cur_start, cur_end, cur_off, cur_off // 3600))

    if (cur_start, cur_end, cur_off) == (london_start, london_end, new_off):
        log("all values already correct; nothing to do.")
        return 0

    drift = max(abs(london_start - cur_start), abs(london_end - cur_end),
                abs(off_h - cur_off // 3600))
    if drift > MAX_DRIFT_HOURS and not force:
        log("REFUSING to patch: drift %dh > %dh (suspicious measurement). "
            "Inspect manually, or rerun with --force."
            % (drift, MAX_DRIFT_HOURS))
        send_telegram("FTTimeCal: drift %dh too big, NOT patched "
                      "(measured UTC%+d vs current UTC%+d)."
                      % (drift, off_h, cur_off // 3600))
        return 1

    if not apply:
        log("DRY RUN (add --apply to write):")
        log("  LONDON_START_HOUR %d -> %d" % (cur_start, london_start))
        log("  LONDON_END_HOUR   %d -> %d" % (cur_end, london_end))
        log("  SERVER_TIME_OFFSET %d -> %d" % (cur_off, new_off))
        return 0

    files = apply_patch(london_start, london_end, new_off)
    if not files:
        log("mismatch but nothing patched (regex miss) -- investigate.")
        send_telegram("FTTimeCal: patch produced NO changes; investigate.")
        return 1

    subprocess.run(["cmd", "/c", COMPILE_BAT], capture_output=True, timeout=600)
    subprocess.run(["cmd", "/c", RESTART_RUNNER], capture_output=True, timeout=120)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", RELAUNCH_PS], capture_output=True, timeout=300)

    msg = ("FTTimeCal: patched %s. London %02d-%02dh, offset UTC%+d "
           "(was %02d-%02d / UTC%+d). Runner + MT5 restarting."
           % (", ".join(files), london_start, london_end, off_h,
              cur_start, cur_end, cur_off // 3600))
    log(msg)
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
