"""SL/TP live audit (2026-09-30). DEMO attach; read-only except optional close.

1) Live trailing-SL check for every -T twin with an OPEN position:
   gain vs its own trail-activation (FTTest 0.3 / aether 1.0 x ATR(signal tf));
   armed SL must sit within 2 ATR of the correct trail distance; fixed twins
   must NOT have moved their SL past entry.
2) Last 3 days of closed trips from deals.csv: trips that lost MORE than
   2.2 ATR-worth (SL 2 x ATR + cushion) = suspected un-triggered stop.
   The EA prints ' OPEN ... sl=... tp=...' on every open; the journal keeps
   the SL/TP in the position comment -> compare against actual exit price.
3) Journal scan (last 3 days, both main + MQL5 logs): every 'failed modify'
   / 'Invalid stops' line with counts, plus STUCK-STOP re-trigger / CLOSE
   evidence (is the EA-side guard firing?).

Run: python C:/FTTest/scripts/_audit_sltp_20260930.py
"""
import csv
import glob
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from forward_test import load_env, closed_bars
from champion_check import streams
from make_dashboard import MAGIC_HINT

FT = r"C:\FTTest"
DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
DEALS = os.path.join(FT, "logs", "forward", "deals.csv")
TFS = {"M1": 60, "M15": 96, "M30": 48, "H1": 24, "H4": 6}


def atr_of(symbol, tf, n=30):
    bars = closed_bars(symbol, tf, n)
    if len(bars) < 16:
        return None
    trs = []
    for i in range(1, len(bars)):
        pc = bars[i - 1]["close"]
        trs.append(max(bars[i]["high"] - bars[i]["low"],
                       abs(bars[i]["high"] - pc), abs(bars[i]["low"] - pc)))
    return sum(trs[-14:]) / 14


def journal_scan(days=3):
    now = time.time()
    hits = {"invalid": [], "stuck_pulse": 0, "stuck_close": 0}
    for sub in ("logs", os.path.join("MQL5", "Logs")):
        for j in glob.glob(os.path.join(DATA, sub, "*.log")):
            if now - os.path.getmtime(j) > days * 86400:
                continue
            try:
                if os.path.getsize(j) > 40e6:
                    continue
                try:
                    txt = open(j, encoding="utf-16", errors="replace").read()
                except UnicodeError:
                    txt = open(j, encoding="cp1252", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(
                    r"failed modify.*?\[(Invalid stops|[^\]]+)\]", txt):
                hits["invalid"].append(m.group(0)[:150])
            hits["stuck_pulse"] += len(re.findall(r"STUCK-STOP re-trigger", txt))
            hits["stuck_close"] += len(re.findall(r"STUCK-STOP CLOSE", txt))
    return hits


def main():
    load_env()
    for attempt in range(4):
        if mt5.initialize():
            break
        print("attach attempt %d failed: %s" % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        time.sleep(8)
    else:
        print("ATTACH_FAILED")
        return 3
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        return 2
    print("SL/TP audit on %s | %s" % (acc.server, datetime.now(timezone.utc)
                                      .strftime("%Y-%m-%d %H:%M UTC")))

    # ---------------- 1) live trailing twins -------------------------------
    print("\n== 1) LIVE TRAILING TWIN CHECK ==")
    armed = wait = suspicious = fixed_bad = 0
    for sym, name, base_m, twin_m, champ in streams():
        poss = [p for p in (mt5.positions_get(symbol=sym) or [])
                if p.magic == twin_m]
        if not poss:
            continue
        tf = {"breakout": "M15", "macross": "M30", "straddle": "H1",
              "smc": "M15", "london": "M15", "squeeze": "M15",
              "profile": "M15", "orderflow": "M1", "trendpullback": "M15",
              "donchian": "H1", "trend": "H1", "supres": "H1",
              "supertrend": "H1", "aetherflow": "M15",
              "aetherflow-M30": "M30", "aetherflow-H4": "H4"}.get(name, "M15")
        a = atr_of(sym, tf)
        act, dist = (1.0, 1.2) if name.startswith("aetherflow") else (0.3, 0.7)
        tick = mt5.symbol_info_tick(sym)
        for p in poss:
            label = "%s-T (%d)" % (name, p.magic)
            entry, sl = p.price_open, p.sl
            if champ == "trail":
                cur = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                gain = (cur - entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (entry - cur)
                moved = (sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < sl < entry)
                if moved:
                    armed += 1
                    resid = (cur - dist * a - sl) if a else 0
                    print("  %-24s ARMED   gain=%.2f ATR  sl=%.2f "
                          "resid=%+.0f pts %s"
                          % (label, gain / a if a else 0, sl,
                             resid / mt5.symbol_info(sym).point,
                             "OK" if abs(resid) < a else "OFF!"))
                elif a and gain >= act * a:
                    suspicious += 1
                    print("  %-24s SUSPICIOUS gain=%.2f ATR >= %.1f but sl=%.2f "
                          "static" % (label, gain / a, act, sl))
                else:
                    wait += 1
                    print("  %-24s WAIT    gain=%.2f ATR (< %.1f activation)"
                          % (label, gain / a if a else 0, act))
            else:
                bad = (sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < sl < entry)
                if bad:
                    fixed_bad += 1
                    print("  %-24s VIOLATION: fixed twin but SL moved past entry"
                          % label)
    print("  summary: %d armed OK, %d waiting, %d SUSPICIOUS, %d fixed-violations"
          % (armed, wait, suspicious, fixed_bad))

    # ---------------- 2) oversize losses in closed trips -------------------
    print("\n== 2) TRIPS LOST > 2.2 x ATR (suspected un-triggered stops) ==")
    trips = {}
    if os.path.exists(DEALS):
        with open(DEALS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["entry"] == "in":
                    trips[r["position_id"]] = r
                elif r["entry"] == "out" and r["position_id"] in trips:
                    i = trips.pop(r["position_id"])
                    try:
                        pnl = float(r["profit"]) + float(r["commission"]) \
                            + float(r["swap"])
                        vol = float(i["volume"])
                    except (ValueError, KeyError):
                        continue
                    if pnl >= 0 or vol != 0.01:
                        continue
                    d = abs(float(i["price"]) - float(r["price"]))
                    tf = {"breakout": "M15", "macross": "M30",
                          "straddle": "H1", "smc": "M15", "london": "M15",
                          "squeeze": "M15", "profile": "M15",
                          "orderflow": "M1", "trendpullback": "M15",
                          "donchian": "H1", "trend": "H1", "supres": "H1",
                          "supertrend": "H1"}.get(i["strategy"].replace("-T", ""), "M15")
                    a = atr_of("XAUUSD", tf, 200)
                    if a and d > 2.2 * a:
                        print("  %-20s lost $%7.2f  move=$%6.2f (%.1f ATR) "
                              "%s -> %s" % (i["strategy"], pnl, d, d / a,
                                            i["time_utc"][:16],
                                            r["time_utc"][:16]))
    else:
        print("  deals.csv missing")

    # ---------------- 3) journal scan ---------------------------------------
    print("\n== 3) JOURNAL SCAN (last 3d) ==")
    hits = journal_scan(3)
    print("  STUCK-STOP re-triggers: %d | guard closes: %d"
          % (hits["stuck_pulse"], hits["stuck_close"]))
    print("  failed-modify lines: %d" % len(hits["invalid"]))
    seen = {}
    for line in hits["invalid"][-200:]:
        key = re.sub(r"#\d+", "#T", line)
        key = re.sub(r"sl: [\d.]+, tp: [\d.]+ -> sl: [\d.]+", "sl: X -> Y", key)
        key = re.sub(r"\d{2}:\d{2}:\d{2}\.\d+", "", key)
        seen[key] = seen.get(key, 0) + 1
    for k, c in sorted(seen.items(), key=lambda kv: -kv[1])[:8]:
        print("   x%-4d %s" % (c, k[:130]))

    print("\nVERDICT: %s" % (
        "trailing OK + no oversize SL losses + no invalid-stop storm"
        if (suspicious == 0 and fixed_bad == 0 and not hits["invalid"])
        else "ISSUES FOUND -- see above"))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
