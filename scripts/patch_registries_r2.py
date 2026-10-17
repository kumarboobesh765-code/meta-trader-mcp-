r"""Patch repo registries to match retirement round-2 (run LOCALLY after the
Oct 1 verdict, with the families the gate approved):

  python scripts/patch_registries_r2.py --families trendpullback,donchian
  python scripts/patch_registries_r2.py --families all
  python scripts/patch_registries_r2.py --dry --families squeeze

Edits (idempotent):
  1. make_ea_profile.py  -> add each family's charts to RETIRED_CHARTS (and
     mark its NEW_STRATS entry retired so regeneration never resurrects it)
  2. champion_check.py   -> drop the family from EXTRA_XAU (or skip via
     RETIRED_STRATS for core names), add to RETIRED_STRATS
  3. _diag_ea_health.py  -> remove/comment its EXPECTED entries, adjust the
     want-N count message
Prints a summary of every hunk applied. forward_test.py MAGICS and
make_dashboard.py history rows are intentionally NEVER touched (append-only
contract).
"""
import argparse
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CHARTS = {"trendpullback": (25, 26), "donchian": (27, 28),
          "trend": (29, 30), "squeeze": (13, 14)}
MAGICS = {"trendpullback": (930010, 940010), "donchian": (930011, 940011),
          "trend": (930012, 940012), "squeeze": (930007, 940007)}
EXTRA_NAME = {"trendpullback": "trendpullback", "donchian": "donchian",
              "trend": "trend", "squeeze": None}  # squeeze lives in STRAT_NAMES


def patch_make_profile(fam, dry):
    p = os.path.join(ROOT, "scripts", "make_ea_profile.py")
    s = open(p, encoding="utf-8").read()
    orig = s
    # 1) RETIRED_CHARTS tuple grows
    m = re.search(r"RETIRED_CHARTS = \(([^)]*)\)", s)
    if not m:
        return "%s: RETIRED_CHARTS not found!" % p
    have = {int(x.strip()) for x in m.group(1).split(",") if x.strip()}
    want = set(CHARTS[fam])
    if want <= have:
        pass
    else:
        merged = sorted(have | want)
        new = "RETIRED_CHARTS = (%s)" % ", ".join(str(c) for c in merged)
        s = s[:m.start()] + new + s[m.end():]
        # extend the family comment above it
        s = s.replace(
            "# RETIRED 2026-09-30 (worst PF families since session start):",
            "# RETIRED 2026-09-30 (worst PF families since session start):\n"
            "#   round-2 2026-10-01: %s charts %s" % (fam, CHARTS[fam]), 1)
    if s != orig:
        if not dry:
            open(p, "w", encoding="utf-8").write(s)
        return "%s: RETIRED_CHARTS += %s" % (p, sorted(want - have))
    return "%s: already patched" % p


def patch_champion(fam, dry):
    p = os.path.join(ROOT, "scripts", "champion_check.py")
    s = open(p, encoding="utf-8").read()
    orig = s
    name = EXTRA_NAME[fam]
    changed = []
    if name:
        # drop from EXTRA_XAU (EXTRA families live there)
        s2 = re.sub(r"\s*\(\"%s\", \d+\)," % name, "", s, count=1)
        if s2 != s:
            s = s2
            changed.append("dropped from EXTRA_XAU")
    # every retired family (EXTRA or core name) must enter RETIRED_STRATS
    if '"%s"' % fam not in s:
        s = re.sub(r"RETIRED_STRATS = frozenset\(\(",
                   "RETIRED_STRATS = frozenset((\"%s\", " % fam, s, count=1)
        changed.append("added to RETIRED_STRATS")
    if s != orig:
        if not dry:
            open(p, "w", encoding="utf-8").write(s)
        return "%s: %s (%s)" % (p, ", ".join(changed), fam)
    return "%s: already patched (%s)" % (p, fam)


def patch_diag(fam, dry, want):
    p = os.path.join(ROOT, "scripts", "_diag_ea_health.py")
    s = open(p, encoding="utf-8").read()
    orig = s
    ea = "FTTest_%s" % fam
    notes = []
    s2 = re.sub(r'\s*\("%s", "XAUUSD", "\w+", \d+\),' % ea,
                "    # %s RETIRED 2026-10-01 (round-2)" % ea, s, count=1)
    if s2 != s:
        s = s2
        notes.append("EXPECTED entry commented out")
    elif ea in s:
        notes.append("entry present but pattern unmatched -- CHECK MANUALLY")
    else:
        notes.append("was never listed (nothing to do)")
    # keep the want-count text truthful
    if "want 31" in s and want != 31:
        s = s.replace("want 31", "want %d" % want)
        s = re.sub(r"meanrev 3/4 \+ profile 21/22 retired 2026-09-30",
                   "meanrev 3/4 + profile 21/22 retired 2026-09-30, "
                   "round-2 2026-10-01", s, count=1)
        notes.append("want count -> %d" % want)
    if s != orig:
        if not dry:
            open(p, "w", encoding="utf-8").write(s)
        return "%s: %s (%s)" % (p, "; ".join(notes), ea)
    return "%s: already patched (%s)" % (p, "; ".join(notes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", required=True,
                    help="comma list of trendpullback,donchian,trend,squeeze "
                         "or 'all'")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    fams = list(CHARTS) if a.families.strip().lower() == "all" \
        else [f.strip() for f in a.families.split(",")]
    bad = [f for f in fams if f not in CHARTS]
    if bad:
        raise SystemExit("unknown families: %s" % bad)
    want = 31 - 2 * len(fams)
    for f in fams:
        print(patch_make_profile(f, a.dry))
        print(patch_champion(f, a.dry))
        print(patch_diag(f, a.dry, want))
    print("\nnext: run python scripts/make_ea_profile.py, deploy the 3 patched "
          "files + regenerate/delete chr, keep forward_test.py MAGICS untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
