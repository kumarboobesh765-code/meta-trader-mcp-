"""One-shot READ-ONLY EA rig health check (VPS). No mt5 calls anywhere.

Checks:
  1. terminal64/python process census
  2. runner (logger) stdout freshness + last lines
  3. MT5 journal scan: every expected EA instance loaded (20 charts)
  4. recent error lines in main + MQL5 (Experts) journals
  5. compiled .ex5 files + chart profile count
  6. scheduled tasks status
  7. watchdog log tail + first-fill marker
Run: python C:\\FTTest\\scripts\\_diag_ea_health.py
"""
import datetime as dt
import glob
import os
import re
import subprocess

NOW = dt.datetime.now()
FT = r"C:\FTTest"
RUNNER_OUT = os.path.join(FT, "logs", "forward_test_stdout.txt")
WATCHDOG_LOG = os.path.join(FT, "logs", "vps_watchdog.log")
DEALS = os.path.join(FT, "logs", "forward", "deals.csv")
MARKER = os.path.join(FT, "logs", "watchdog_first_fill.sent")

EXPECTED = [  # (name, symbol, tf, min_count)
    ("FTTest_breakout", "XAUUSD", "M15", 1),
    # FTTest_meanrev RETIRED 2026-09-30 (charts 3/4, PF 0.19)
    ("FTTest_macross", "XAUUSD", "M30", 1),
    ("FTTest_straddle", "XAUUSD", "H1", 1),
    ("FTTest_smc", "XAUUSD", "M15", 1),
    ("FTTest_london", "XAUUSD", "M15", 1),
    ("FTTest_squeeze", "XAUUSD", "M15", 1),
    # FTTestMultiEA FX charts RETIRED 2026-09-28 (XAU-only rig)
    ("FTTest_supertrend", "XAUUSD", "H1", 2),
    ("AetherFlowEA", "XAUUSD", "M15", 2),
    ("AetherFlowEA", "XAUUSD", "M30", 2),
    ("XAUUSD_SmartMoney_VolumeProfile_EA", "XAUUSD", "M1", 1),
]
BENIGN = ("10018",)  # market closed retcode


def hr(tag):
    print("-" * 74)
    print(tag)


def find_data_dir():
    cands = glob.glob(r"C:\Users\*\AppData\Roaming\MetaQuotes\Terminal\*")
    cands += glob.glob(r"C:\Program Files\MetaTrader*")
    best, best_t = None, 0.0
    for c in cands:
        if os.path.isdir(os.path.join(c, "MQL5")) and os.path.isdir(os.path.join(c, "logs")):
            for j in glob.glob(os.path.join(c, "logs", "*.log")):
                t = os.path.getmtime(j)
                if t > best_t:
                    best, best_t = c, t
    return best


# 1) processes ---------------------------------------------------------------
hr("1) PROCESSES")
out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                     text=True, errors="replace").stdout
procs = {}
for line in out.splitlines():
    parts = [p.strip('"') for p in line.split('","')]
    if len(parts) >= 2:
        procs.setdefault(parts[0].lower(), []).append(parts[1])
for name in ("terminal64.exe", "python.exe"):
    pids = procs.get(name, [])
    print("  %-15s x%d  %s" % (name, len(pids), ",".join(pids[:10])))
mem = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "(Get-CimInstance Win32_OperatingSystem | "
                      "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | "
                      "ConvertTo-Json)"],
                     capture_output=True, text=True, errors="replace").stdout
try:
    import json
    mv = json.loads(mem)
    tot = float(mv["TotalVisibleMemorySize"]) / 1e6
    free = float(mv["FreePhysicalMemory"]) / 1e6
    print("  RAM: %.2f GB total, %.2f GB free (%.0f%% used)"
          % (tot, free, 100 * (tot - free) / max(tot, 1e-9)))
except Exception as e:
    print("  RAM check skipped (%s)" % e)

# 2) runner logger -----------------------------------------------------------
hr("2) RUNNER LOGGER (FTForwardTest)")
if os.path.exists(RUNNER_OUT):
    age = NOW.timestamp() - os.path.getmtime(RUNNER_OUT)
    txt = open(RUNNER_OUT, errors="replace").read()
    print("  stdout age: %.0f s  (%s)" % (age, "FRESH" if age < 600 else "STALE!"))
    print("  'forward test STARTED' count: %d" % txt.count("forward test STARTED"))
    last = txt.rfind("forward test STARTED")
    sess = txt[last:] if last >= 0 else ""
    errs = [l for l in sess.splitlines()
            if re.search(r"REFUSING|FAILED|error", l, re.I)]
    print("  errors/warnings in current session: %d" % len(errs))
    for l in errs[-5:]:
        print("    ", l.strip()[:150])
    print("  last 8 lines:")
    for l in [x for x in sess.splitlines() if x.strip()][-8:]:
        print("    ", l.strip()[:150])
else:
    print("  MISSING:", RUNNER_OUT)

# 3) deals -------------------------------------------------------------------
hr("3) DEALS.CSV")
if os.path.exists(DEALS):
    with open(DEALS) as f:
        rows = [l for l in f.read().strip().splitlines() if l.strip()]
    print("  data rows: %d" % max(0, len(rows) - 1))
    if len(rows) > 1:
        per = {}
        for l in rows[1:]:
            c = l.split(",")
            if len(c) >= 8:
                s, entry = c[3], c[7]
                d = per.setdefault(s, {"in": 0, "out": 0, "last": c[0][:16]})
                d[entry] = d.get(entry, 0) + 1
                d["last"] = max(d["last"], c[0][:16])
        print("  streams with activity: %d" % len(per))
        for s in sorted(per):
            d = per[s]
            print("    %-22s in=%-3d out=%-3d last=%s" % (s, d["in"], d["out"], d["last"]))
else:
    print("  deals.csv not present yet (created on first logged deal)")

# 4) journals ----------------------------------------------------------------
hr("4) MT5 EA INSTANCE VERIFICATION (journal scan, last 4 days)")
data = find_data_dir()
print("  data dir:", data)
loaded = {}
err_lines = []
if data:
    for sub, tag in (("logs", "main"), (os.path.join("MQL5", "Logs"), "mql5")):
        for j in glob.glob(os.path.join(data, sub, "*.log")):
            if NOW.timestamp() - os.path.getmtime(j) > 4 * 86400:
                continue
            try:
                if os.path.getsize(j) > 30 * 1e6:
                    continue
                # MT5 journals are usually UTF-16LE; fall back to ANSI.
                try:
                    txt = open(j, encoding="utf-16", errors="replace").read()
                except (UnicodeError, UnicodeDecodeError):
                    txt = open(j, encoding="cp1252", errors="replace").read()
                if "loaded successfully" not in txt and "expert" not in txt.lower():
                    continue
            except OSError:
                continue
            for m in re.finditer(r"expert\s+(\w+)\s+\(([^,)]+),([^)]+)\)\s+loaded successfully", txt):
                loaded.setdefault((m.group(1), m.group(2), m.group(3)), 0)
                loaded[(m.group(1), m.group(2), m.group(3))] += 1
            for line in txt.splitlines():
                low = line.lower()
                if ("error" in low or "failed" in low or "invalid" in low) \
                        and not any(b in line for b in BENIGN):
                    err_lines.append((tag, os.path.basename(j), line.strip()[:170]))

    print("  loaded EA instances found:")
    for k in sorted(loaded):
        print("    %-36s (%s,%s) x%d" % (k[0], k[1], k[2], loaded[k]))
    ok = True
    for name, sym, tf, need in EXPECTED:
        got = sum(v for (n, s, t), v in loaded.items()
                  if n == name and s == sym and (tf is None or t == tf))
        status = "OK" if got >= need else "MISSING"
        if got < need:
            ok = False
        print("  %-38s %-8s %-4s want>=%d got=%d  %s" % (name, sym, tf or "?", need, got, status))
    print("  ALL %d EXPECTED EA INSTANCES PRESENT" % sum(e[3] for e in EXPECTED)
          if ok else "  !! SOME EAs DID NOT LOAD -- see above")

    hr("4b) RECENT JOURNAL ERROR LINES (excl. 10018 market-closed)")
    seen = {}
    for tag, fn, line in err_lines[-400:]:
        seen.setdefault(line, [0, tag, fn])
        seen[line][0] += 1
    for line, (cnt, tag, fn) in sorted(seen.items(), key=lambda kv: -kv[1][0])[:15]:
        print("   x%-4d [%s %s] %s" % (cnt, tag, fn, line[:140]))
    if not seen:
        print("   none")
else:
    print("  !! MT5 data dir not found")

# 5) ex5 + profile -----------------------------------------------------------
hr("5) COMPILED EAs + CHART PROFILE")
if data:
    ex5s = glob.glob(os.path.join(data, "MQL5", "Experts", "**", "*.ex5"), recursive=True)
    for e in sorted(ex5s):
        base = os.path.basename(e)
        if base.lower().startswith(("fttest", "aetherflow", "xauusd_smartmoney")):
            t = dt.datetime.fromtimestamp(os.path.getmtime(e))
            print("  %-42s %s" % (base, t.strftime("%Y-%m-%d %H:%M")))
    prof = glob.glob(os.path.join(data, "MQL5", "Profiles", "Charts", "FTTest", "*.chr"))
    print("  chart profile .chr count: %d (want 31; chart15 slot retired, "
          "meanrev 3/4 + profile 21/22 retired 2026-09-30)" % len(prof))

# 6) tasks -------------------------------------------------------------------
hr("6) SCHEDULED TASKS")
for t in ("FTForwardTest", "VPSWatchdog", "FTCheck", "FTVerdict", "FTTimeCal",
          "FTMondaySmoke", "MTRelaunch"):
    q = subprocess.run(["schtasks", "/Query", "/TN", t, "/FO", "LIST"],
                       capture_output=True, text=True, errors="replace")
    if q.returncode != 0:
        print("  %-16s NOT FOUND" % t)
        continue
    fields = {}
    for line in q.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    print("  %-16s status=%-12s lastresult=%-6s next=%s"
          % (t, fields.get("status", "?"), fields.get("last result", "?"),
             fields.get("next run time", "?")))

# 7) watchdog ----------------------------------------------------------------
hr("7) WATCHDOG")
print("  first-fill marker exists:", os.path.exists(MARKER))
if os.path.exists(WATCHDOG_LOG):
    lines = open(WATCHDOG_LOG, errors="replace").read().splitlines()
    print("  last 10 watchdog lines:")
    for l in lines[-10:]:
        print("    ", l.strip()[:160])
else:
    print("  no watchdog log at", WATCHDOG_LOG)

hr("DONE")
