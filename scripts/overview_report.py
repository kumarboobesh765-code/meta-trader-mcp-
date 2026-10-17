r"""Forward-test trade overview. Runs ON THE VPS.

A) account snapshot (equity.csv tail)   B) closed-trade overview
C) per-strategy-family results          D) XAU vs FX split
E) best/worst streams                   F) open positions with floating P&L

Usage: python C:/FTTest/scripts/overview_report.py [--tg]
"""
import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import MAGICS, load_env

DEALS_CSV = r"C:\FTTest\logs\forward\deals.csv"
EQUITY_CSV = r"C:\FTTest\logs\forward\equity.csv"
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
SERVER_UTC_OFFSET = 3   # deals.csv time_utc labels are broker wall clock (UTC+3)


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def family(stream):
    s = stream
    for suf in ("-EA-T", "-EA", "-T"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    if s.startswith("aetherflow-M30"):
        return "aetherflow-M30"
    if s.startswith("aetherflow"):
        return "aetherflow-M15"
    return s.split("-")[0]


def load_deals():
    deals = []
    with open(DEALS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            try:
                deals.append({
                    "magic": int(row["magic"]), "stream": row["strategy"],
                    "symbol": row["symbol"], "side": row["type"],
                    "entry": row["entry"], "vol": float(row["volume"]),
                    "price": float(row["price"]),
                    "pnl": float(row["profit"]) + float(row["commission"])
                           + float(row["swap"]),
                    "pid": row["position_id"],
                    "t": datetime.fromisoformat(row["time_utc"]),
                })
            except (KeyError, ValueError):
                continue
    return deals


def round_trips(deals):
    """[(stream, symbol, t_out, pnl, t_in, side, vol)] closed round trips."""
    opens, trips = {}, []
    for d in deals:
        if d["entry"] == "in":
            opens[(d["magic"], d["pid"])] = d
        elif d["entry"] == "out":
            o = opens.pop((d["magic"], d["pid"]), None)
            trips.append({
                "stream": d["stream"], "symbol": d["symbol"],
                "t": d["t"], "pnl": d["pnl"],
                "dur_h": ((d["t"] - o["t"]).total_seconds() / 3600.0
                          if o else 0.0),
                "side": o["side"] if o else d["side"],
                "vol": o["vol"] if o else d["vol"],
            })
    return trips


def stat_block(trips):
    if not trips:
        return None
    net = sum(t["pnl"] for t in trips)
    wins = [t for t in trips if t["pnl"] > 0]
    losses = [t for t in trips if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    return {"n": len(trips), "net": net,
            "win": 100.0 * len(wins) / len(trips),
            "pf": (gw / gl) if gl > 0 else float("inf")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tg", action="store_true")
    args = ap.parse_args()

    load_env()
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1

    deals = load_deals()
    trips = round_trips(deals)

    out = ["FTTest trade overview (deals.csv, %d rows)" % len(deals)]

    # A) equity snapshot
    try:
        with open(EQUITY_CSV, newline="") as f:
            last = list(csv.reader(f))[-1]
        stamp = last[0].replace("T", " ")[:16]
        out.append("A) account %s: balance=%s equity=%s (csv %s UTC)"
                   % (acc.login, last[1], last[2], stamp))
    except (OSError, IndexError):
        out.append("A) account %s: balance=%.2f equity=%.2f (live)"
                   % (acc.login, acc.balance, acc.equity))

    # B) overview
    allstat = stat_block(trips)
    first = min(t["t"] for t in trips).strftime("%Y-%m-%d") if trips else "n/a"
    today_label = (datetime.now(timezone.utc)
                   - timedelta(hours=SERVER_UTC_OFFSET)).date()
    td_trips = [t for t in trips if t["t"].date() == today_label]
    td = stat_block(td_trips)
    out.append("B) closed round trips: %d since %s | net %+.2f | win %.0f%% | PF %s"
               % (allstat["n"], first, allstat["net"], allstat["win"],
                  ("%.2f" % allstat["pf"]) if allstat["pf"] != float("inf") else "inf"))
    if td:
        out.append("   today(%s): %d trips, net %+.2f" % (today_label, td["n"], td["net"]))

    # C) per family
    fam = defaultdict(list)
    for t in trips:
        fam[family(t["stream"])].append(t)
    rows = []
    for name, ts in fam.items():
        s = stat_block(ts)
        rows.append((s["net"], name, s))
    rows.sort(reverse=True)
    out.append("C) per-strategy family (sorted by net):")
    for net, name, s in rows:
        tag = "WORKED WELL" if net > 0 else "LOSING"
        out.append("   %-16s n=%-4d net=%+9.2f  win=%3.0f%%  PF=%-5s  %s"
                   % (name, s["n"], s["net"], s["win"],
                      ("%.2f" % s["pf"]) if s["pf"] != float("inf") else "inf",
                      tag))    # D) per-pair split (sorted by net, worst to best bottom-up)
    bysym = defaultdict(list)
    for t in trips:
        bysym[t["symbol"]].append(t)
    out.append("D) per-pair results (sorted by net):")
    srows = sorted(((stat_block(ts), sym) for sym, ts in bysym.items()),
                   key=lambda x: x[0]["net"])
    for s, sym in srows:
        out.append("   %-7s n=%-4d net=%+9.2f  win=%3.0f%%"
                   % (sym, s["n"], s["net"], s["win"]))

    # E) best/worst streams
    strm = defaultdict(list)
    for t in trips:
        strm[t["stream"]].append(t)
    srows = sorted(((stat_block(ts)["net"], name) for name, ts in strm.items()),
                   reverse=True)
    out.append("E) top streams:  " + " | ".join(
        "%s %+.2f" % (n, v) for v, n in srows[:5]))
    out.append("   worst streams: " + " | ".join(
        "%s %+.2f" % (n, v) for v, n in srows[-5:]))

    # F) open positions
    poss = mt5.positions_get() or []
    out.append("F) open positions: %d" % len(poss))
    fl_total = 0.0
    for p in sorted(poss, key=lambda p: p.magic):
        fl = p.profit + p.swap
        fl_total += fl
        name = MAGICS.get(p.magic, "magic %d" % p.magic)
        # p.time encodes broker wall clock (UTC+3) as epoch: true open time
        # is p.time - 3h, so age = now_utc - (p.time - 3h)
        age_h = max(0.0, (datetime.now(timezone.utc).timestamp() - p.time)
                    / 3600.0 + SERVER_UTC_OFFSET)
        out.append("   %-22s %-7s %-4s %.2f @ %.*f sl=%.*f tp=%.*f fl=%+8.2f  age~%.0fh"
                   % (name, p.symbol, "BUY" if p.type == mt5.POSITION_TYPE_BUY
                      else "SELL", p.volume, 2 if "XAU" in p.symbol else 5,
                      p.price_open, 2 if "XAU" in p.symbol else 5, p.sl,
                      2 if "XAU" in p.symbol else 5, p.tp, fl, age_h))
    out.append("   floating total: %+.2f | balance %.2f equity %.2f"
               % (fl_total, acc.balance, acc.equity))
    mt5.shutdown()

    text = "\n".join(out)
    print(text)
    if args.tg:
        send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
