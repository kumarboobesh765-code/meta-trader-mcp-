"""Generate .set presets for FTTestEA: 7 strategies x fixed/trailing SL twins.

Each preset is loadable in the EA's Inputs dialog or the Strategy Tester:
drag FTTestEA on a chart -> Inputs -> Load -> pick the .set file.

Usage: python scripts/make_presets.py
Output: vps/bundle/presets/*.set  (also bundled for VPS deployment)
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "vps", "bundle", "presets")

# ENUM_TIMEFRAMES numeric values as MQL5 stores them in .set files
TF = {"M15": 15, "M30": 30, "H1": 16385}

# name, InpStrategy ordinal, timeframe, fixed-twin magic (trailing = +10000)
# EA magic range 9300xx/9400xx is separate from the Python runner's
# 9100xx/9200xx so the two implementations never collide on one account.
STRATS = [
    ("breakout", 0, "M15", 930001),
    ("meanrev",  1, "M15", 930002),
    ("macross",  2, "M30", 930003),
    ("straddle", 3, "H1",  930004),
    ("smc",      4, "M15", 930005),
    ("london",   5, "M15", 930006),
    ("squeeze",  6, "M15", 930007),
]

TEMPLATE = """\
; FTTestEA preset - {name} twin, {mode} SL (magic {magic})
; Signal timeframe: {tf}. Load via EA Inputs -> Load.
InpStrategy={strat}
InpTimeframe={tfv}
InpLots=0.01000000
InpMagic={magic}
InpUseTrailing={trail}
InpTrailActAtr=1.00000000
InpTrailDistAtr=1.20000000
InpTrailStepAtr=0.30000000
InpAllowReal=false
InpDeviationPts=50
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    made = []
    for name, strat, tf, magic_fixed in STRATS:
        for mode, magic, trail in (("fixed", magic_fixed, "false"),
                                   ("trailing", magic_fixed + 10000, "true")):
            fname = "FTTestEA_%s_%s.set" % (name, mode)
            with open(os.path.join(OUT, fname), "w") as f:
                f.write(TEMPLATE.format(name=name, mode=mode, magic=magic,
                                        trail=trail, strat=strat, tf=tf,
                                        tfv=TF[tf]))
            made.append(fname)
    print("wrote %d presets to %s" % (len(made), OUT))
    for m in made:
        print("  " + m)


if __name__ == "__main__":
    main()
