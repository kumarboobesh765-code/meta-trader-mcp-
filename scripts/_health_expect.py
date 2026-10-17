"""Derive the expected per-chart rig contract from the generated bundle.

The bundle profile (vps/bundle/profile/FTTest/*.chr) is the AUTHORITATIVE
statement of what each chart should be: which expert is attached, which magic,
whether trailing is on, and the exact trail triple. This script parses it and
emits _health_expect.json for _health_check.py to diff against the VPS copies.

Nothing here touches the network -- it is pure local parsing so the expectations
can never drift from what we actually intend to deploy.

Usage: python scripts/_health_expect.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROF = os.path.join(ROOT, "vps", "bundle", "profile", "FTTest")
OUT = os.path.join(ROOT, "scripts", "_health_expect.json")


def parse(path):
    with open(path, encoding="utf-16") as f:
        txt = f.read()

    d = {"file": os.path.basename(path)}

    m = re.search(r"^symbol=(\S+)", txt, re.M)
    d["symbol"] = m.group(1) if m else None
    m = re.search(r"^period_type=(\d+)", txt, re.M)
    m2 = re.search(r"^period_size=(\d+)", txt, re.M)
    d["tf"] = ("%sh" % m2.group(1)) if (m and m.group(1) == "1") else ("%sm" % m2.group(1))

    m = re.search(r"name=(\S+)\npath=Experts\\FTTest\\(\S+)", txt)
    d["expert"] = m.group(1) if m else None
    d["ex5"] = m.group(2) if m else None

    # The rig has TWO EA contracts: the FTTest family (InpMagic, InpUseTrailing,
    # ATR triple) and the user's own SMVP binary (InpMagicNumber, R-based
    # trail). Read whichever is present and record which contract it is, so the
    # health checker knows which fields are even meaningful for this chart.
    d["contract"] = "fttest" if re.search(r"^InpMagic=", txt, re.M) else "smvp"

    if d["contract"] == "fttest":
        m = re.search(r"^InpMagic=(\d+)", txt, re.M)
        d["magic"] = int(m.group(1)) if m else None
        m = re.search(r"^InpUseTrailing=(\S+)", txt, re.M)
        d["trailing"] = (m.group(1) == "true") if m else None
        trip = []
        for k in ("InpTrailActAtr", "InpTrailDistAtr", "InpTrailStepAtr"):
            m = re.search(r"^%s=(\S+)" % k, txt, re.M)
            trip.append(m.group(1) if m else "?")
        d["trail"] = "/".join(trip)
    else:
        m = re.search(r"^InpMagicNumber=(\d+)", txt, re.M)
        d["magic"] = int(m.group(1)) if m else None
        d["trailing"] = None       # R-based trail, not the ATR contract
        d["trail"] = "R-based"

    m = re.search(r"^InpLots=(\S+)", txt, re.M)
    d["lots"] = m.group(1) if m else None
    m = re.search(r"^InpAllowReal=(\S+)", txt, re.M)
    d["allow_real"] = m.group(1) if m else None
    return d


def main():
    rows = []
    for name in sorted(os.listdir(PROF)):
        if not (name.startswith("chart") and name.endswith(".chr")):
            continue
        rows.append(parse(os.path.join(PROF, name)))

    # chart15 is retired too (FTTestMultiEA/FX, XAU-only rig since 2026-09-28)
    # but unlike the others it is deleted inline rather than in RETIRED_CHARTS.
    # chart29 (trend FIXED, magic 930012) retired 2026-10-05 with user approval:
    # worst arm in the rig at -$249.98 over 10 trips (-$25.00/trip, 10% win).
    # CONSOLIDATION 2026-10-05 (user chose "making money"): retire the families
    # that lose in BOTH arms and drop only the losing arm where the twin wins.
    #   whole family: aetherflow-H4 (33,34) donchian (27,28) squeeze (13,14)
    #                 supertrend (35,36) vwaprev (31,32)   ~-$793 combined
    #   losing arm:   macross FIXED (5) breakout TRAIL (2) aetherflow-M15 FIXED (17)
    # NOTE: the approved scope named "trendpullback TRAIL (940009)" but 940009
    # is fixfade; trendpullback is 930010/940010 whose charts 25/26 were
    # already retired, so no trendpullback arm remained to drop. 940009/fixfade
    # has zero closed trips in era1 and is deliberately KEPT (untested).
    # 2026-10-06: vwaprev (31,32) UN-RETIRED (live -52 was 6-trip noise;
    # 200d backtest +402/301 trips) and sweepabs added (44,45).
    LIVE = tuple(n for n in range(1, 46)
                 if n not in (3, 4, 15, 21, 22, 25, 26, 29, 2, 5, 13, 14, 17,
                              27, 28, 33, 34, 35, 36))
    numbers = sorted(int(r["file"][5:7]) for r in rows)
    assert numbers == list(LIVE), \
        "bundle chart set is not 39-minus-retired: %s" % numbers

    with open(OUT, "w") as f:
        json.dump(rows, f, indent=1)

    for r in rows:
        print("  %-12s %-18s %-4s %-11s magic %-7s trail=%-5s %s"
              % (r["file"], r["expert"], r["tf"], r["symbol"], r["magic"],
                 r["trailing"], r["trail"]))
    print("wrote %d expectations -> %s" % (len(rows), OUT))


if __name__ == "__main__":
    main()