"""AetherFlow EA verification (read-only, mt5 attach): all 4 instances, both
trading modes, fixed/trailing SL behavior. Evidence:
  A. chart inputs for 17-20 (mode, trailing flag, trail params)
  B. journal history: starts, OPENs, trail SL modifies, CLOSEs per magic
  C. open positions per magic: entry/SL/TP + gain-vs-activation check
Run: python C:/FTTest/scripts/_diag_aetherflow.py
"""
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import closed_bars, load_env

NOW = dt.datetime.now()
DATA = r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
PROF = os.path.join(DATA, "MQL5", "Profiles", "Charts", "FTTest")
MAGICS = {950001: "aetherflow (M15 confluence, fixed)",
          960001: "aetherflow-T (M15 confluence, trailing)",
          950002: "aetherflow-M30 (UT-only, fixed)",
          960002: "aetherflow-M30-T (UT-only, trailing)"}


def read_chr(p):
    raw = open(p, "rb").read()
    try:
        return raw.decode("utf-16")
    except UnicodeError:
        return raw.decode("cp1252", errors="replace")


def hr(t):
    print("-" * 70)
    print(t)


hr("A) CHART INPUTS (17-20)")
for i in (17, 18, 19, 20):
    p = os.path.join(PROF, "chart%02d.chr" % i)
    t = read_chr(p)
    mode = re.search(r"InpTradingMode=(\d)", t)
    trail = re.search(r"InpUseTrailing=(\w+)", t)
    act = re.search(r"InpTrailActAtr=([\d.]+)", t)
    dist = re.search(r"InpTrailDistAtr=([\d.]+)", t)
    tf = re.search(r"period_size=(\d+)", t)
    print("  chart%02d  trading_mode=%s  trailing=%-5s  act=%s dist=%s  host_tf=M%s"
          % (i, mode.group(1) if mode else "?", trail.group(1) if trail else "?",
             act.group(1) if act else "?", dist.group(1) if dist else "?",
             tf.group(1) if tf else "?"))

hr("B) JOURNAL EVIDENCE (5 days, per magic)")
stats = {m: {"started": 0, "open": 0, "trail": 0, "close": 0, "last": ""}
         for m in MAGICS}
for j in (glob.glob(os.path.join(DATA, "logs", "*.log"))
          + glob.glob(os.path.join(DATA, "MQL5", "Logs", "*.log"))):
    if NOW.timestamp() - os.path.getmtime(j) > 5 * 86400:
        continue
    try:
        txt = open(j, "rb").read().decode("utf-16", errors="replace")
    except OSError:
        continue
    for line in txt.splitlines():
        mm = re.search(r"\b(950001|960001|950002|960002)\b", line)
        if not mm:
            continue
        m = int(mm.group(1))
        s = stats[m]
        if "started on" in line:
            s["started"] += 1
        elif "trail SL ->" in line:
            s["trail"] += 1
        elif " OPEN " in line:
            s["open"] += 1
        elif " CLOSE " in line:
            s["close"] += 1
        s["last"] = max(s["last"], line.strip()[:120])
for m, s in sorted(stats.items()):
    print("  %d %-38s starts=%d opens=%d trailMods=%d closes=%d"
          % (m, MAGICS[m], s["started"], s["open"], s["trail"], s["close"]))
    print("      last: %s" % s["last"])

hr("C) OPEN POSITIONS (gain vs 1.0 ATR activation for -T twins)")
env = load_env()
if not mt5.initialize():
    print("mt5.initialize failed: %s" % mt5.last_error())
    sys.exit(1)
acc = mt5.account_info()
print("  account %s %s" % (acc.login, acc.server))
tf_of = {950001: "M15", 960001: "M15", 950002: "M30", 960002: "M30"}
any_open = False
for m in sorted(MAGICS):
    poss = [p for p in (mt5.positions_get() or []) if p.magic == m]
    if not poss:
        print("  %d %-38s flat" % (m, MAGICS[m]))
        continue
    any_open = True
    a_bars = closed_bars("XAUUSD", tf_of[m], 30)
    trs = []
    for i in range(1, len(a_bars)):
        pc = a_bars[i - 1]["close"]
        trs.append(max(a_bars[i]["high"] - a_bars[i]["low"],
                       abs(a_bars[i]["high"] - pc), abs(a_bars[i]["low"] - pc)))
    a = sum(trs[-14:]) / 14 if len(trs) >= 14 else None
    tick = mt5.symbol_info_tick("XAUUSD")
    for p in poss:
        trail_twin = (m == 960001 or m == 960002)
        gain = (tick.bid - p.price_open) if p.type == mt5.POSITION_TYPE_BUY \
            else (p.price_open - tick.ask)
        moved = (p.sl > p.price_open) if p.type == mt5.POSITION_TYPE_BUY \
            else (0 < p.sl < p.price_open)
        if trail_twin and a:
            state = ("ARMED-TRAILING (ratcheted)" if moved else
                     ("WAITING (gain %.2f ATR < activation)" % (gain / a)
                      if gain < 1.0 * a else "SHOULD-HAVE-TRAILED -- CHECK"))
        elif trail_twin:
            state = "ARMED-TRAILING (ratcheted)" if moved else "WAITING (no ATR)"
        else:
            state = "fixed twin: SL static = %s" % ("OK" if not moved else "MOVED?! ")
        print("  %d %-38s %s @ %.2f sl=%.2f tp=%.2f gain=%+.2f  -> %s"
              % (m, MAGICS[m], "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                 p.price_open, p.sl, p.tp, gain, state))
if not any_open:
    print("  (no open aetherflow positions right now)")
mt5.shutdown()
print("-" * 70)
print("DONE")
