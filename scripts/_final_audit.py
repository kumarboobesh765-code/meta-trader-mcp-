"""Final rig audit: every EA loaded, trailing-SL config + live behavior.

Runs ON THE VPS. Read-only, no Telegram. Sections:
  A) charts: parse all .chr -> name/magic/InpUseTrailing vs expected (WINNER)
  B) journal: "started" lines per EA, trail SL modifies / failures per magic
  C) live positions: SL placement vs entry (ratchet evidence / fixed-twin
     violations / missing SL)
  D) runner + watchdog health
"""
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import MAGICS, WINNER, load_env

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
PROF = os.path.join(TERM, "MQL5", "Profiles", "Charts", "FTTest")
ELOGS = os.path.join(TERM, "MQL5", "Logs")
RUNNER_LOG = r"C:\FTTest\logs\forward_test_stdout.txt"

REPORT = []


def out(s):
    print(s)
    REPORT.append(s)


def expected_trail(magic):
    """True/False where the A/B rule is clear; None = report-only."""
    name = MAGICS.get(magic)
    if magic in (930015, 930016, 930017):
        return None            # liquiditysweep port / user binary / dayopen
    if 940000 < magic < 950000 and name:
        base = name.replace("-EA-T", "").replace("-EA", "").replace("-T", "")
        w = WINNER.get(("XAUUSD", base))
        return None if w is None else (w == "trail")
    if 930000 < magic < 940000 and name:
        return False           # fixed base of a core family
    if magic in (950001, 950002, 950003):
        return False
    if magic in (960001, 960002, 960003):
        return True
    return None


def main():
    load_env()
    out("=== A) CHART CONFIG (profile .chr files) ===")
    charts = []
    for p in sorted(os.listdir(PROF)):
        if not p.endswith(".chr"):
            continue
        try:
            txt = open(os.path.join(PROF, p), "rb").read().decode(
                "utf-16", errors="replace")
        except OSError:
            continue
        name = re.search(r"name=(\S+)", txt)
        magic = re.search(r"InpMagic=(\d+)", txt)
        trail = re.search(r"InpUseTrailing=(true|false)", txt)
        charts.append({
            "chart": p, "name": name.group(1) if name else "?",
            "magic": int(magic.group(1)) if magic else None,
            "trail": (trail.group(1) == "true") if trail else None})
    out("charts: %d" % len(charts))
    problems = []
    for c in charts:
        exp = expected_trail(c["magic"]) if c["magic"] else None
        mark = ""
        if exp is not None and c["trail"] is not None and c["trail"] != exp:
            mark = "  <-- MISMATCH (expected %s)" % ("trail" if exp else "fixed")
            problems.append("%s %s magic=%s trail=%s expected=%s"
                            % (c["chart"], c["name"], c["magic"], c["trail"], exp))
        out("  %-13s %-22s magic=%-8s trail=%-5s%s"
            % (c["chart"], c["name"], c["magic"], c["trail"], mark))

    out("\n=== B) JOURNAL (today) ===")
    jname = datetime.now(timezone.utc).strftime("%Y%m%d") + ".log"
    # journal uses VPS-local date; try today and yesterday, newest first
    cands = sorted([f for f in os.listdir(ELOGS) if re.match(r"\d{8}\.log$", f)],
                   reverse=True)[:2]
    jpath = os.path.join(ELOGS, cands[0])
    txt = open(jpath, "rb").read().decode("utf-16", errors="replace")
    out("journal: %s" % cands[0])
    starts = re.findall(r"(\d{6}) started on XAUUSD", txt)
    from collections import Counter
    sc = Counter(starts)
    out("EA starts (this journal): %d magics, %d lines"
        % (len(sc), len(starts)))
    for m in sorted(sc):
        out("   %s x%d" % (m, sc[m]))
    ok_mods = Counter(re.findall(r"(\d{6}) trail SL ->", txt))
    bad_mods = Counter(re.findall(r"(\d{6}) trail modify FAILED", txt))
    stuck = len(re.findall(r"STUCK-STOP", txt))
    out("trail SL modifies OK: %s" % (dict(ok_mods) or "{}"))
    out("trail modify FAILED : %s" % (dict(bad_mods) or "{}"))
    out("stuck-stop closes    : %d" % stuck)
    # fixed magics must never appear in ok_mods
    for m in ok_mods:
        if expected_trail(int(m)) is False:
            problems.append("magic %s is expected FIXED but has %d trail "
                            "modifies" % (m, ok_mods[m]))
    for m in bad_mods:
        problems.append("magic %s had %d FAILED trail modifies"
                        % (m, bad_mods[m]))

    out("\n=== C) LIVE POSITIONS (SL vs entry) ===")
    if not mt5.initialize():
        out("mt5.initialize failed: %s" % (mt5.last_error(),))
    else:
        acc = mt5.account_info()
        out("account %s bal=%.2f eq=%.2f" % (acc.login, acc.balance,
                                             acc.equity))
        poss = mt5.positions_get() or []
        out("open positions: %d" % len(poss))
        for p in sorted(poss, key=lambda x: x.magic):
            name = MAGICS.get(p.magic, "magic %d" % p.magic)
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            sl_side = ("profit-side" if (p.sl > p.price_open) == is_buy
                       and p.sl != 0 else "loss-side/initial")
            exp = expected_trail(p.magic)
            fl = p.profit + p.swap
            line = ("  %-14s %-7s %-4s %.2f @ %8.2f sl=%8.2f tp=%8.2f "
                    "fl=%+7.2f  sl=%s" % (name, p.symbol,
                                          "BUY" if is_buy else "SELL", p.volume,
                                          p.price_open, p.sl, p.tp, fl,
                                          sl_side))
            if p.sl == 0:
                line += "  <-- NO SL!"
                problems.append("%s magic %s has NO SL" % (name, p.magic))
            if exp is False and p.sl != 0 and sl_side == "profit-side":
                line += "  <-- FIXED twin with profit-side SL!"
                problems.append("%s magic %s (fixed) SL on profit side"
                                % (name, p.magic))
            if exp is True and sl_side == "profit-side":
                line += "  (ratchet OK)"
            out(line)
        mt5.shutdown()

    out("\n=== D) RUNNER / WATCHDOG ===")
    try:
        age = time.time() - os.path.getmtime(RUNNER_LOG)
        size = os.path.getsize(RUNNER_LOG)
        tail = open(RUNNER_LOG, "rb").read()[-200000:].decode(
            "utf-8", errors="replace")
        fails = tail.count("FAILED retcode=")
        out("runner log: age=%.0fs size=%d recent FAILED retcode=%d"
            % (age, size, fails))
        if age > 600:
            problems.append("runner log stale (%.0fs)" % age)
    except OSError as e:
        out("runner log unreadable: %r" % e)
        problems.append("runner log unreadable")
    import subprocess
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"],
                       capture_output=True, text=True)
    pys = [l for l in r.stdout.splitlines() if "python.exe" in l]
    out("python processes: %d" % len(pys))
    r2 = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                        capture_output=True, text=True)
    out("terminal64 running: %s" % ("yes" if "terminal64.exe" in r2.stdout
                                    else "NO"))
    if "terminal64.exe" not in r2.stdout:
        problems.append("terminal64 not running")

    out("\n=== PROBLEMS ===")
    if problems:
        for x in problems:
            out("  !! " + x)
    else:
        out("  none")
    try:
        with open(r"C:\FTTest\logs\final_audit.txt", "w",
                  encoding="utf-8") as f:
            f.write("\n".join(REPORT))
        out("\nreport -> C:\\FTTest\\logs\\final_audit.txt")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
