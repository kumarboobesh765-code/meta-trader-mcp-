"""Ground-truth check: parse the FTTest chart profile (.chr) files to see which
EA + inputs run on each of the 20 charts, then substring-scan recent MT5 main
journals for each EA name's 'loaded successfully' lines, and summarize today's
per-EA (MQL5\\Logs) error lines. READ-ONLY, no mt5 calls."""
import datetime as dt
import glob
import os
import re
import sys

NOW = dt.datetime.now()
DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
PROF = os.path.join(DATA, "MQL5", "Profiles", "Charts", "FTTest")


def read_maybe_utf16(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-16")
    except UnicodeError:
        return raw.decode("cp1252", errors="replace")


def hr(t):
    print("-" * 74)
    print(t)


hr("A) CHART PROFILE (.chr) -- EA per chart")
charts = []
for f in sorted(glob.glob(os.path.join(PROF, "*.chr"))):
    txt = read_maybe_utf16(f)
    fields = {}
    for line in txt.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("<"):
            k, v = line.split("=", 1)
            k = k.strip()
            if k in ("symbol", "period", "expert", "name") or "magic" in k.lower():
                fields[k] = v.strip()
            # MT5 stores inputs like: InpX=value||hash||...
            if k.startswith("Inp") and "magic" in k.lower():
                fields["magic_input"] = v.split("|")[0].strip()
    charts.append((os.path.basename(f), fields))
for name, f in charts:
    print("  %-12s sym=%-8s tf=%-5s expert=%-42s magic=%s" % (
        name.replace(".chr", ""), f.get("symbol", "?"), f.get("period", "?"),
        f.get("expert", "?")[:42], f.get("magic_input", f.get("Magic", "?"))))

hr("B) JOURNAL LOAD SCAN (substring per EA name, main logs, last 5 days)")
names = ["FTTest_breakout", "FTTest_meanrev", "FTTest_macross", "FTTest_straddle",
         "FTTest_smc", "FTTest_london", "FTTest_squeeze", "FTTest_profile",
         "FTTest_orderflow", "FTTest_trendpullback", "FTTest_donchian", "FTTestEA",
         "FTTestMultiEA", "AetherFlowEA", "XAUUSD_SmartMoney_VolumeProfile_EA",
         "StraddleV2_XAUUSD"]
counts = {n: 0 for n in names}
last_load = {n: "" for n in names}
for j in glob.glob(os.path.join(DATA, "logs", "*.log")):
    if NOW.timestamp() - os.path.getmtime(j) > 5 * 86400:
        continue
    try:
        txt = read_maybe_utf16(j)
    except OSError:
        continue
    for line in txt.splitlines():
        if "loaded successfully" not in line:
            continue
        for n in names:
            if n in line:
                counts[n] += 1
                last_load[n] = max(last_load[n], line[:60])
for n in names:
    print("  %-38s loads=%-4d last: %s" % (n, counts[n], last_load[n].strip()[:55]))

hr("C) TODAY'S PER-EA ERRORS (MQL5\\Logs)")
today = glob.glob(os.path.join(DATA, "MQL5", "Logs", "*.log"))
today = [f for f in today if NOW.timestamp() - os.path.getmtime(f) < 86400]
errs = {}
for j in today:
    try:
        txt = read_maybe_utf16(j)
    except OSError:
        continue
    for line in txt.splitlines():
        low = line.lower()
        if ("error" in low or "failed" in low or "cannot" in low
                or "invalid" in low or "initialization failed" in low):
            if "10018" in line or "market closed" in low:
                continue
            key = line.strip()[:130]
            errs[key] = errs.get(key, 0) + 1
print("  per-EA log files today:", len(today))
if errs:
    for k, c in sorted(errs.items(), key=lambda kv: -kv[1])[:20]:
        print("   x%-4d %s" % (c, k))
else:
    print("  no error lines in today's EA logs")

hr("D) OPEN POSITIONS PER MAGIC (from deals.csv last 'in' entries)")
deals = os.path.join(r"C:\FTTest", "logs", "forward", "deals.csv")
if os.path.exists(deals):
    ins, outs = {}, {}
    with open(deals) as f:
        next(f)
        for line in f:
            c = line.split(",")
            if len(c) < 8:
                continue
            strat, entry, pos = c[3], c[7], c[4]
            if entry == "in":
                ins[pos] = strat
            else:
                outs[pos] = strat
    open_pos = [s for p, s in ins.items() if p not in outs]
    from collections import Counter
    print("  open positions by stream:", dict(Counter(open_pos)))
hr("DONE")
