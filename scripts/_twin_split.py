"""Fixed-vs-trailing TWIN SPLIT for the whole rig. Runs ON THE VPS.

The since-day-one report groups by `family`, which strips the "-T" suffix and
therefore COLLAPSES each fixed/trailing pair into one row. That hides the one
question the rig exists to answer: for a family showing -$382, is it the fixed
twin bleeding, the trailing twin bleeding, or both? You cannot retire a family
or flip a twin until you know which arm is at fault.

This splits every magic into its arm and prints, per family, the fixed and
trailing rows side by side plus the delta and which arm actually won.

Magic -> (family, arm) is the AUTHORITATIVE map. It is written out longhand
rather than derived from a naming convention because:
  * the deployer logs a trailing twin at magic+10000 for FTTest families, but
    AetherFlow uses 95xxxx (fixed) / 96xxxx (trailing) -- a different scheme;
  * retired magics (930002/940002 meanrev, 930008/940008 profile,
    930010/940010 trendpullback) still appear in history and must keep their
    real family/arm labels even though their charts are gone;
  * 26092501 is the user's SMVP binary, which has no twin at all.

READ-ONLY. Usage: python C:\\FTTest\\scripts\\_twin_split.py
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\FTTest\scripts")
import MetaTrader5 as mt5

# magic -> (family, arm)   arm is FIXED | TRAIL | SOLO
MAGICS = {
    930001: ("breakout", "FIXED"),      940001: ("breakout", "TRAIL"),
    930002: ("meanrev", "FIXED"),       940002: ("meanrev", "TRAIL"),
    930003: ("macross", "FIXED"),       940003: ("macross", "TRAIL"),
    930004: ("straddle", "FIXED"),      940004: ("straddle", "TRAIL"),
    930005: ("smc", "FIXED"),           940005: ("smc", "TRAIL"),
    930006: ("london", "FIXED"),        940006: ("london", "FIXED"),
    930007: ("squeeze", "FIXED"),       940007: ("squeeze", "TRAIL"),
    930008: ("profile", "FIXED"),       940008: ("profile", "TRAIL"),
    930009: ("fixfade", "FIXED"),       940009: ("fixfade", "TRAIL"),
    930010: ("trendpullback", "FIXED"), 940010: ("trendpullback", "TRAIL"),
    930011: ("donchian", "FIXED"),      940011: ("donchian", "TRAIL"),
    930012: ("trend", "FIXED"),         940012: ("trend", "TRAIL"),
    930013: ("vwaprev", "FIXED"),       940013: ("vwaprev", "TRAIL"),
    930014: ("supertrend", "FIXED"),    940014: ("supertrend", "TRAIL"),
    930015: ("liquiditysweep", "SOLO"),
    930016: ("liqsweep-binary", "SOLO"),
    930017: ("dayopen", "SOLO"),
    930018: ("swing", "FIXED"),           940018: ("swing", "TRAIL"),
    930019: ("swing-m30", "FIXED"),       940019: ("swing-m30", "TRAIL"),
    930020: ("sweepabs", "FIXED"),        940020: ("sweepabs", "TRAIL"),
    930021: ("grid", "SOLO"),
    930022: ("gridclone", "SOLO"),
    930023: ("gridbestrr", "SOLO"),
    950001: ("aetherflow-M15", "FIXED"),   960001: ("aetherflow-M15", "TRAIL"),
    950002: ("aetherflow-M30", "FIXED"),   960002: ("aetherflow-M30", "TRAIL"),
    950003: ("aetherflow-H4", "FIXED"),    960003: ("aetherflow-H4", "TRAIL"),
    26092501: ("smvp", "SOLO"),
    0: ("unknown", "SOLO"),
}


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

    @property
    def pf(self):
        if self.gl > 0:
            return self.gp / self.gl
        return float("inf") if self.gp > 0 else 0.0

    @property
    def win(self):
        return 100.0 * self.wins / self.n if self.n else 0.0

    @property
    def avg(self):
        return self.net / self.n if self.n else 0.0


def pf_s(s):
    return "inf" if s.pf == float("inf") else "%.2f" % s.pf


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error())
        return 1

    acc = mt5.account_info()
    print("account %s (%s)  balance=%.2f  equity=%.2f"
          % (acc.login, acc.server, acc.balance, acc.equity))

    frm = datetime(2026, 9, 20, tzinfo=timezone.utc)
    deals = mt5.history_deals_get(frm, datetime.now(timezone.utc) + timedelta(days=1))
    print("deals: %d\n" % len(deals))

    arms = defaultdict(Agg)          # (family, arm) -> Agg
    unknown = defaultdict(float)

    for d in deals:
        if d.type == mt5.DEAL_TYPE_BALANCE:
            continue
        fam, arm = MAGICS.get(int(d.magic), ("magic_%s" % d.magic, "SOLO"))
        if fam.startswith("magic_"):
            unknown[int(d.magic)] += d.profit
        a = arms[(fam, arm)]
        a.add_costs(d.commission, d.swap)
        if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            a.add_close(d.profit)

    fams = sorted(set(f for f, _ in arms))
    have = [f for f in fams
            if arms.get((f, "FIXED")) or arms.get((f, "TRAIL")) or arms.get((f, "SOLO"))]

    print("=" * 100)
    print("PER-FAMILY TWIN SPLIT   (net is after commission+swap)")
    print("=" * 100)
    print("%-18s %-7s %5s %10s %6s %7s %9s" %
          ("family", "arm", "n", "net", "win%", "PF", "avg"))
    for f in have:
        for arm in ("FIXED", "TRAIL", "SOLO"):
            s = arms.get((f, arm))
            if not s or not s.n:
                continue
            print("%-18s %-7s %5d %+10.2f %5.0f%% %7s %+9.2f"
                  % (f, arm, s.n, s.net, s.win, pf_s(s), s.avg))
        fx, tr = arms.get((f, "FIXED")), arms.get((f, "TRAIL"))
        if fx and tr and fx.n and tr.n:
            # Compare PER TRADE, not raw totals: the two arms do not always
            # have the same trade count, and a raw-net delta on unequal n is
            # meaningless.
            d = tr.avg - fx.avg
            verdict = "TRAIL" if d > 0 else "FIXED"
            print("%-18s %-7s %5s %10s %6s %7s %+9.2f  <- per-trade edge, %s wins by %.2f"
                  % ("", "EDGE", "", "", "", "", d, verdict, abs(d)))
        print()

    print("=" * 100)
    print("VERDICT: which arm is actually at fault in each losing family")
    print("=" * 100)
    for f in have:
        fx, tr = arms.get((f, "FIXED")), arms.get((f, "TRAIL"))
        if not (fx and tr and fx.n and tr.n):
            continue
        tot = fx.net + tr.net
        if tot >= 0:
            continue
        worse = fx if fx.avg < tr.avg else tr
        better = tr if worse is fx else fx
        wname = "FIXED" if worse is fx else "TRAIL"
        print("%-18s pair net %+9.2f | losing arm = %-6s (%+6.2f/trip, n=%d)"
              % (f, tot, wname, worse.avg, worse.n))
        print("%-18s surviving arm = %-6s %+6.2f/trip over n=%d -> %s"
              % ("", "FIXED" if better is fx else "TRAIL", better.avg, better.n,
                 "family is salvageable, drop the losing arm"
                 if better.net > 0 else "BOTH arms lose -- retire the family"))

    if unknown:
        print("\nunmapped magics (history with no contract mapping):")
        for m, v in sorted(unknown.items(), key=lambda kv: -abs(kv[1])):
            print("  magic %-9s %+10.2f" % (m, v))

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)