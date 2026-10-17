"""Since-day-one strategy report.
Era 0: archive_fusion_465983/deals.csv (old account, Sep 24-25 pilot)
Era 1: MT5 deal history on current account (complete, fills Sep 26-27 gap)
Usage: python _report_since_start.py
"""
import sys
import csv
from datetime import datetime, timezone
from collections import defaultdict

import MetaTrader5 as mt5

LOG = r"C:\FTTest\logs"
ARCHIVE_DEALS = LOG + r"\archive_fusion_465983\deals.csv"

# Known magic->stream fallbacks (csv map takes priority)
FALLBACK = {
    930001: 'breakout', 940001: 'breakout-T',
    930002: 'meanrev', 940002: 'meanrev-T',
    930003: 'macross', 940003: 'macross-T',
    930004: 'straddle', 940004: 'straddle-T',
    930005: 'smc', 940005: 'smc-T',
    930006: 'london', 940006: 'london-T',
    930007: 'squeeze', 940007: 'squeeze-T',
    930008: 'profile', 940008: 'profile-T',
    930009: 'orderflow', 940009: 'orderflow-T',
    930010: 'trendpullback', 940010: 'trendpullback-T',
    930011: 'donchian', 940011: 'donchian-T',
    930018: 'swing', 940018: 'swing-T',
    930019: 'swing-m30', 940019: 'swing-m30-T',
    930020: 'sweepabs', 940020: 'sweepabs-T',
    950001: 'aetherflow', 960001: 'aetherflow-T',
    950002: 'aetherflow-M30', 960002: 'aetherflow-M30-T',
    26092501: 'smvp',
}


def family(stream):
    x = stream
    if x.endswith('-T'):
        x = x[:-2]
    if x.endswith('-EA'):
        x = x[:-3]
    return x


class Agg:
    def __init__(self):
        self.n = 0
        self.net = 0.0
        self.wins = 0
        self.gp = 0.0
        self.gl = 0.0

    def add_close(self, pnl):
        self.n += 1
        self.net += pnl
        if pnl > 0:
            self.wins += 1
            self.gp += pnl
        elif pnl < 0:
            self.gl += -pnl

    def add_costs(self, comm, swap):
        self.net += comm + swap


def print_table(stats, title):
    print(title)
    rows = sorted(stats.items(), key=lambda kv: -kv[1].net)
    print(f"  {'family':<16}{'n':>5}{'net':>11}{'win%':>6}{'PF':>8}")
    for fam, s in rows:
        if s.gl > 0:
            pf = f"{s.gp / s.gl:.2f}"
        else:
            pf = "inf" if s.gp > 0 else "-"
        print(f"  {fam:<16}{s.n:>5}{s.net:>+11.2f}{100 * s.wins / max(1, s.n):>5.0f}%{pf:>8}")
    tot_n = sum(s.n for s in stats.values())
    tot_net = sum(s.net for s in stats.values())
    tot_w = sum(s.wins for s in stats.values())
    gp = sum(s.gp for s in stats.values())
    gl = sum(s.gl for s in stats.values())
    pf = f"{gp / gl:.2f}" if gl > 0 else "inf"
    print(f"  {'TOTAL':<16}{tot_n:>5}{tot_net:>+11.2f}{100 * tot_w / max(1, tot_n):>5.0f}%{pf:>8}")
    print()


# ---------------- Era 0: archive csv ----------------
def era0():
    stats = defaultdict(Agg)
    try:
        with open(ARCHIVE_DEALS, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['entry'] != 'out':
                    continue
                pnl = float(row['profit'] or 0) + float(row['commission'] or 0) + float(row['swap'] or 0)
                stats[family(row['strategy'])].add_close(pnl)
    except FileNotFoundError:
        print("era0: archive csv missing, skipped")
        return None
    return stats


# ---------------- Era 1: MT5 history ----------------
def era1():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error())
        sys.exit(1)
    acc = mt5.account_info()
    print(f"account {acc.login} ({acc.server}): balance={acc.balance:.2f} equity={acc.equity:.2f}")

    from_d = datetime(2026, 9, 20, tzinfo=timezone.utc)
    deals = mt5.history_deals_get(from_d, datetime.now(timezone.utc) + __import__('datetime').timedelta(days=1))
    print(f"deals pulled from broker history: {len(deals)}")

    # magic -> stream name from current deals csv
    name_by_magic = {}
    for path in (LOG + r"\forward\deals.csv", ARCHIVE_DEALS):
        try:
            with open(path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    try:
                        name_by_magic[int(row['magic'])] = row['strategy']
                    except (ValueError, KeyError):
                        pass
        except FileNotFoundError:
            pass

    def name_of(m):
        return name_by_magic.get(m, FALLBACK.get(m, f"magic_{m}"))

    stats = defaultdict(Agg)
    daily = defaultdict(float)
    daily_ea = defaultdict(float)
    deposit = 0.0
    first_ts = None
    last_ts = None
    trips = 0
    tot_net = 0.0
    ea_net = 0.0
    non_ea = []
    wins = 0
    for d in deals:
        if d.type == mt5.DEAL_TYPE_BALANCE:
            deposit += d.profit
            continue
        fam = family(name_of(d.magic))
        s = stats[fam]
        s.add_costs(d.commission, d.swap)
        if d.entry == mt5.DEAL_ENTRY_OUT or d.entry == mt5.DEAL_ENTRY_OUT_BY:
            pnl = d.profit
            s.add_close(pnl)
            day = datetime.fromtimestamp(d.time, tz=timezone.utc).strftime('%m-%d')
            net = pnl + d.commission + d.swap
            daily[day] += net
            trips += 1
            tot_net += net
            if pnl > 0:
                wins += 1
            # magic 0 means nothing tagged the order -- a manual/stray trade,
            # not rig performance. Two such positions opened 2026-09-18 and
            # were closed 2026-09-28 for +$360 combined, which is most of what
            # the era headline used to claim. Per the 2026-10-05 decision the
            # EA-only figure is the headline and the all-in figure is shown
            # alongside it, so nothing is hidden but the two are never
            # conflated again.
            if d.magic == 0:
                non_ea.append((d.time, d.symbol, net))
            else:
                ea_net += net
                daily_ea[day] += net
            ts = d.time
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

    print(f"deposits (balance ops): {deposit:.2f}")
    if first_ts:
        f_ = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        l_ = datetime.fromtimestamp(last_ts, tz=timezone.utc)
        print(f"first trade: {f_.isoformat()}  last: {l_.isoformat()}  (times are broker UTC+3 wall clock)")
    print(f"ERA1 EA-ONLY  trips: {trips - len(non_ea)}  net: {ea_net:+.2f}  "
          f"win: {100 * wins / max(1, trips - len(non_ea)):.0f}%   <-- HEADLINE")
    print(f"ERA1 ALL-IN    trips: {trips}  net: {tot_net:+.2f}  "
          f"win: {100 * wins / max(1, trips):.0f}%")
    if non_ea:
        print(f"  (untagged magic-0 closes excluded from headline: "
              f"{len(non_ea)} trips, {sum(n for _, _, n in non_ea):+.2f})")
        for ts_, sym, net_ in sorted(non_ea):
            print("    %s %-7s %+9.2f"
                  % (datetime.fromtimestamp(ts_, tz=timezone.utc)
                     .strftime('%Y-%m-%d %H:%M'), sym, net_))
    print()
    print("daily net (broker clock) -- EA-ONLY is the headline, all-in shown after it:")
    for day in sorted(daily):
        extra = ""
        if day in daily_ea:
            extra = "   [all-in {:+.2f}]".format(daily[day])
        print(f"  {day}: {daily_ea.get(day, 0.0):+.2f}{extra}")
    print()
    mt5.shutdown()
    return stats, deposit


s0 = era0()
if s0:
    print_table(s0, "ERA 0 - pilot on old account (Sep 24-25, archive csv):")
s1, dep = era1()
print_table(s1, "ERA 1 - current account 26122844 (Sep 26 -> now, MT5 history):")
