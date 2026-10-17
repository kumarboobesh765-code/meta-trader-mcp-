r"""Twin-pair A/B performance report (today's deals.csv = the current session).
Runs ON THE VPS.

For every EA stream and its -T trailing twin: closed round trips, net, win%,
who won (fixed vs trail), plus current floating P&L of still-open positions.

Usage: python C:/FTTest/scripts/pair_report.py [--tg]
"""
import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import MAGICS, load_env

from overview_report import send_telegram, round_trips, load_deals


def stat(ts):
    net = sum(t["pnl"] for t in ts)
    wins = len([t for t in ts if t["pnl"] > 0])
    return net, len(ts), (100.0 * wins / len(ts) if ts else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tg", action="store_true")
    args = ap.parse_args()

    load_env()
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    deals = load_deals()
    trips = round_trips(deals)

    by_stream = defaultdict(list)
    for t in trips:
        by_stream[t["stream"]].append(t)

    # pair streams: <base> vs <base>-T
    bases = sorted({s[:-2] if s.endswith("-T") else s for s in by_stream})
    rows = []
    for base in bases:
        f_ts = by_stream.get(base, [])
        t_ts = by_stream.get(base + "-T", [])
        if not f_ts and not t_ts:
            continue
        fnet, fn, fwin = stat(f_ts)
        tnet, tn, twin = stat(t_ts)
        rows.append((fnet + tnet, base, fnet, fn, fwin, tnet, tn, twin))
    rows.sort(reverse=True)

    out = ["FTTest twin-pair A/B (deals.csv session %s)"
           % (min(t["t"] for t in trips).strftime("%Y-%m-%d") if trips else "n/a")]
    out.append("%-18s %16s   %16s   %8s  %s"
               % ("PAIR", "FIXED (n/win%)", "TRAIL -T (n/win%)", "DIFF", "WINNER"))
    total = 0.0
    for comb, base, fnet, fn, fwin, tnet, tn, twin in rows:
        total += comb
        diff = tnet - fnet
        winner = ("tie" if abs(diff) < 1.0 else
                  "TRAIL" if diff > 0 else "FIXED")
        out.append("%-18s %+9.2f (%2d/%3.0f%%)   %+9.2f (%2d/%3.0f%%)   %+7.2f  %s"
                   % (base, fnet, fn, fwin, tnet, tn, twin, diff, winner))
    out.append("TOTAL closed net: %+.2f" % total)

    # floating P&L per stream (open positions right now)
    fl = defaultdict(float)
    n_open = 0
    for p in (mt5.positions_get() or []):
        name = MAGICS.get(p.magic)
        if name:
            fl[name] += p.profit + p.swap
            n_open += 1
    out.append("")
    out.append("open positions: %d, floating by stream:" % n_open)
    for name in sorted(fl):
        out.append("   %-22s %+8.2f" % (name, fl[name]))
    out.append("   %-22s %+8.2f" % ("FLOATING TOTAL", sum(fl.values())))
    out.append("balance %.2f  equity %.2f" % (acc.balance, acc.equity))
    mt5.shutdown()

    text = "\n".join(out)
    print(text)
    if args.tg:
        send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
