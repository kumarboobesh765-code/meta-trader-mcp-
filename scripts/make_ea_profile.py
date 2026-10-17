"""Generate the MT5 'FTTest' chart profile: 14 XAUUSD charts with FTTestEA
already attached (7 strategies x fixed/trailing twins). Deploy it and set it as
the last-used profile so it auto-loads when the user starts MT5.

Format reverse-engineered from the VPS's own MQL5\\Profiles\\Charts\\Default\\chart02.chr
(a real chart with StraddleV2 attached): the <expert> block sits between
windows_total and <window>; inputs are plain key=value lines.

Usage: python scripts/make_ea_profile.py     -> vps/bundle/profile/FTTest/
"""

import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "vps", "bundle", "profile", "FTTest")

# period_type: 0 = minutes, 1 = hours (learned from real .chr files:
# M1=0,1  M30=0,30  H1=1,1  H4=1,4  D1=1,24)
PERIOD = {"M1": (0, 1), "M15": (0, 15), "M30": (0, 30), "H1": (1, 1), "H4": (1, 4)}

# name, InpStrategy ordinal, chart timeframe, fixed magic (trailing = +10000)
CHARTS = [
    ("breakout", 0, "M15", 930001),
    ("meanrev",  1, "M15", 930002),
    ("macross",  2, "M30", 930003),
    ("straddle", 3, "H1",  930004),
    ("smc",      4, "M15", 930005),
    ("london",   5, "M15", 930006),
    ("squeeze",  6, "M15", 930007),
]

# XAUUSD -T charts whose 30d trailing-vs-fixed verdict favored a STATIC SL
# (scripts/backtest_trailing_check.py): trailing loses on meanrev and can
# never act on london (TP = +1 ATR = activation threshold; 30d backtest:
# fixed -$73.60 beats every trail config, tightest -$85.20 -- trailing LOSES).
# straddle was removed 10/01: trail cuts its bleed $256/30d (-899.8 -> -641.0).
XAU_FIXED_TWINS = {"london"}

# ---------------------------------------------------------------- trail config
# Baseline trail ATR triple (ACT/DIST/STEP) for the FTTest twins. Every
# .chr template below bakes this in as a literal, so it lives here once and is
# substituted into the templates -- otherwise a change has to be replicated
# across ~10 template strings and they silently drift apart.
TRAIL_DEFAULT = (0.1, 0.3, 0.05)

# TIGHTENED 2026-10-02 at the user's request ("strategies go good in profit
# then reverse to loss" -> protect open profit sooner and ratchet faster).
# Evidence:
#   scripts/_trail_tighter_sweep.py  (100d, $0.24/trade, pessimistic fills)
#     EVERY probed family improves MONOTONICALLY as the trail tightens:
#     breakout +1435->+1777->+1947->+2069, macross +622->+740->+859->+854,
#     smc +294->+523->+588->+645, squeeze +752->+794->+856->+929,
#     trend +2078->+2407->+2675->+2880; win% 68->76, PF 1.72->2.16.
#   scripts/_trail_tighter_windows.py (same data split into 5 sequential
#   NON-OVERLAPPING windows, to catch "the pooled number is one lucky regime"):
#     breakout beats the deployed trail in 5/5 windows at EVERY tighter level,
#     and the worst leave-one-out total is +1402 vs +982 deployed.
# 0.05/0.15/0.02 is chosen over the more extreme 0.04/0.12/0.02: the two are
# within noise of each other, and 0.05 keeps a slightly wider cushion under the
# stop so ordinary spread/vol spikes cannot shake it out on a live tick.
# Applied ONLY to the families the sweeps actually measured. donchian,
# vwaprev, fixfade, trendpullback and supertrend keep their own verdicts
# (supertrend is deliberately LOOSER at 0.5/0.8/0.20 -- tighter bleeds on the
# coarse H1 ATR), and london stays fixed-only per XAU_FIXED_TWINS.
TRAIL_TIGHT = (0.05, 0.15, 0.02)
#   scripts/_trail_untested_families.py (100d + 5 windows, the four deployed
#   trail twins the tightening sweep never measured):
#     donchian       +761 -> +1111 (5/5 windows, worst-LOO +803)  [APPLIED]
#     trendpullback  +1704 -> +2222 (5/5 windows) -- 5/5 too, but its charts
#       25/26 are RETIRED (see RETIRED_CHARTS), so there is nothing live to
#       tighten; it is left out of the set to keep that intent explicit.
#   fixfade and vwaprev are DELIBERATELY EXCLUDED: every one of their signals
#   falls in window 1 and windows 2-5 contain ZERO trades, so the grid has
#   nothing to grade (all configs tie exactly). Tightening them would be a
#   guess on 7 and 27 trades that are not distributed across regimes.
#   supertrend stays excluded too -- it is deliberately LOOSER (0.5/0.8/0.20)
#   because tighter bleeds on its coarse H1 ATR.
TRAIL_TIGHT_FAMILIES = {"breakout", "macross", "smc", "squeeze", "trend",
                        "donchian"}


def trail_lines(triple):
    """The three InpTrail* lines as they appear inside a .chr template."""
    return ("InpTrailActAtr=%s\nInpTrailDistAtr=%s\nInpTrailStepAtr=%s\n"
            % triple)


def apply_trail(content, triple):
    """Swap the default trail triple baked into a rendered .chr for `triple`."""
    return content.replace(trail_lines(TRAIL_DEFAULT), trail_lines(triple))


def hdr(**kw):
    """HEADER.format with the default trail triple supplied automatically, so
    the ~11 template call sites don't each restate ta/td/ts."""
    kw.setdefault("ta", TRAIL_DEFAULT[0])
    kw.setdefault("td", TRAIL_DEFAULT[1])
    kw.setdefault("ts", TRAIL_DEFAULT[2])
    return HEADER.format(**kw)


def tighten_if_probed(content, family, trail):
    """Apply TRAIL_TIGHT to a chart whose family the sweeps actually measured.

    Only the TRAILING twin is rewritten: the fixed twin's InpTrail* inputs are
    inert (InpUseTrailing=false) and leaving them alone keeps the shipped .chr
    diff limited to the charts whose behaviour actually changes."""
    if trail != "true" or family not in TRAIL_TIGHT_FAMILIES:
        return content
    return apply_trail(content, TRAIL_TIGHT)

# Trail inputs TIGHTENED 2026-09-30 per the 90d sweep
# (scripts/_trail_tighten_sweep.py): FTTest twins 0.3/0.7/0.15 ->
# 0.2/0.5/0.10 (+$656/90d summed over the trail twins; supertrend mildly
# prefers the old setting, kept uniform per instruction). AetherFlow twins
# tightened proportionally 1.0/1.2/0.3 -> 0.8/1.0/0.25 (engine not in the
# sweep harness). SMVP untouched (R-based trail, user's own EA).

# Trail inputs (FTTest twins): TIGHTENED 2026-09-30 per the 90d sweep
# (scripts/_trail_tighten_sweep.py): 0.3/0.7/0.15 -> 0.2/0.5/0.10
# (+$656/90d across the trail twins; supertrend slightly prefers the old
# setting, kept uniform per instruction). AetherFlow twins: proportional
# tighten 1.0/1.2/0.3 -> 0.8/1.0/0.25 (engine not sweep-covered).

# chart15 slot: RETIRED (2026-09-28, XAU-only rig decision). FTTestMultiEA
# used to trade the 4 FX pairs from this one chart; all of its strategies
# already run on dedicated XAUUSD charts, so the FX book was removed. The
# chart numbering is unchanged (16-28 keep their numbers).
#
# chart03/04 (meanrev) + chart21/22 (profile): RETIRED 2026-09-30 (worst PF
# families since session start). Their slots are still generated (numbering
# stays stable) and deleted at the end of main() -- see RETIRED_CHARTS.

# chart16: the user's XAUUSD SmartMoney+VolumeProfile scalper (own EA, no
# demo-only rail -- account is demo). FIXED 0.01 lot per user instruction
# 2026-10-01 (was 0.25%% risk compounding) -- aligns SMVP with the rig's
# 0.01-lot convention across all EAs.
SMVP_CHART = {
    "expert_name": "XAUUSD_SmartMoney_VolumeProfile_EA",
    "expert_path": "Experts\\FTTest\\XAUUSD_SmartMoney_VolumeProfile_EA.ex5",
    "symbol": "XAUUSD",
    "tf": "M1",
    "inputs": ("InpMagicNumber=26092501\nInpEntryTF=1\nInpTrendTF=5\n"
               "InpAllowBuy=true\nInpAllowSell=true\nInpOnePositionOnly=true\n"
               "InpMaxTradesPerDay=30\nInpSlippagePoints=30\n"
               "InpFastEMA=20\nInpSlowEMA=50\nInpSwingLookback=35\n"
               "InpImpulseATRPeriod=14\nInpImpulseATRMultiplier=1.20\n"
               "InpZoneMaxAgeBars=80\nInpZoneBufferATR=0.15\n"
               "InpProfileLookbackBars=120\nInpProfileBins=48\n"
               "InpPOCMaxDistanceATR=0.60\nInpRequirePOCConfluence=true\n"
               "InpMinBodyToRange=0.35\nInpMinWickToRange=0.20\n"
               "InpEntryZoneToleranceATR=0.20\nInpRequireTrendFilter=true\n"
               "InpUseRiskPercent=false\nInpRiskPercent=0.25\nInpFixedLot=0.01\n"
               "InpSL_ATR_Multiplier=1.50\nInpTP_RiskReward=1.50\n"
               "InpMinSLPoints=250\nInpMaxSLPoints=2500\nInpMaxLot=2.00\n"
               "InpUseBreakEven=true\nInpBreakEvenTriggerR=0.80\n"
               "InpBreakEvenOffsetPoints=20\nInpUseTrailingStop=true\n"
               "InpTrailStartR=1.00\nInpTrailATRMultiplier=1.00\n"
               "InpTrailMinStepPoints=25\nInpUseChandelierTrail=true\n"
               "InpChandelierLookback=12\nInpMaxSpreadPoints=100\n"
               "InpUseTradingHours=false\nInpStartHour=7\nInpEndHour=22\n"
               "InpAvoidFridayLate=true\nInpFridayCutoffHour=20"),  }

HEADER = """<chart>
id={cid}
symbol=XAUUSD
description=Gold vs US Dollar
period_type={ptype}
period_size={psize}
digits=2
tick_size=0.000000
position_time={now}
scale_fix=0
scale_fixed_min=0.000000
scale_fixed_max=0.000000
scale_fix11=0
scale_bar=0
scale_bar_val=0.000000
scale=4
mode=1
fore=0
grid=1
volume=0
scroll=1
shift=0
shift_size=19.887955
fixed_pos=0.000000
ticker=1
ohlc=0
one_click=0
one_click_btn=0
bidline=1
askline=0
lastline=0
days=0
descriptions=0
tradelines=1
tradehistory=1
window_left=0
window_top=0
window_right=780
window_bottom=290
window_type=1
floating=0
floating_left=0
floating_top=0
floating_right=0
floating_bottom=0
floating_type=1
floating_toolbar=1
floating_tbstate=
background_color=0
foreground_color=16777215
barup_color=65280
bardown_color=65280
bullcandle_color=0
bearcandle_color=16777215
chartline_color=65280
volumes_color=3329330
grid_color=10061943
bidline_color=10061943
askline_color=255
lastline_color=49152
stops_color=255
windows_total=1

<expert>
name=FTTestEA
path=Experts\\FTTest\\FTTestEA.ex5
expertmode=1
<inputs>
InpStrategy={strat}
InpTimeframe={tfv}
InpLots=0.01
InpMagic={magic}
InpUseTrailing={trail}
InpTrailActAtr={ta}
InpTrailDistAtr={td}
InpTrailStepAtr={ts}
InpAllowReal=false
InpDeviationPts=50
</inputs>
</expert>

<window>
height=100.000000
objects=0

<indicator>
name=Main
path=
apply=1
show_data=1
scale_inherit=0
scale_line=0
scale_line_percent=50
scale_line_value=0.000000
scale_fix_min=0
scale_fix_min_val=0.000000
scale_fix_max=0
scale_fix_max_val=0.000000
expertmode=0
fixed_height=-1
</indicator>
</window>
</chart>
"""

# ENUM_TIMEFRAMES numeric values (what MQL5 stores for enum inputs)
TF_VALS = {"M15": 15, "M30": 30, "H1": 16385, "H4": 16388}


def main():
    os.makedirs(OUT, exist_ok=True)
    now = int(time.time())
    n = 0
    # ids must be unique across runs: a fixed base made chart12 collide with
    # stale profile state and MT5 refused to load it ("error loading chart")
    base_id = int(time.time()) * 1000000000
    for name, strat, tf, magic_fixed in CHARTS:
        for mode, magic, trail in (("fixed", magic_fixed, "false"),
                                   ("trailing", magic_fixed + 10000, "true")):
            if mode == "trailing" and name in XAU_FIXED_TWINS:
                trail = "false"   # verdict: fixed manages this -T twin
            n += 1
            ptype, psize = PERIOD[tf]
            content = hdr(
                cid=base_id + n, now=now, ptype=ptype, psize=psize,
                strat=strat, tfv=TF_VALS[tf], magic=magic, trail=trail)
            # per-strategy expert builds: each chart runs the EA NAMED after
            # its strategy (FTTest_breakout.ex5, ...), so the expert list,
            # journal and tooltips all show the strategy name
            content = content.replace(
                "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
                "name=FTTest_%s\npath=Experts\\FTTest\\FTTest_%s.ex5" % (name, name))
            # 2026-10-02 trail tightening -- probed families only (TRAIL_TIGHT)
            content = tighten_if_probed(content, name, trail)
            path = os.path.join(OUT, "chart%02d.chr" % n)
            # MT5 writes .chr as UTF-16 LE with BOM and CRLF endings
            with open(path, "w", encoding="utf-16", newline="") as f:
                f.write(content.replace("\n", "\r\n"))
            print("  chart%02d.chr  %-9s %-4s %-7s magic %d  (FTTest_%s.ex5)" %
                  (n, name, tf, mode, magic, name))

    # chart15: RETIRED -- FTTestMultiEA/FX removed from the rig (XAU-only).
    # Keep the slot number so charts 16-28 never renumber, and self-heal the
    # bundle by deleting a stale chart15.chr.
    n += 1
    stale15 = os.path.join(OUT, "chart15.chr")
    if os.path.exists(stale15):
        os.remove(stale15)
        print("  chart15.chr  REMOVED (FTTestMultiEA retired -- XAU-only rig)")

    # chart16: SMVP EA (user's own scalper, FIXED 0.01 lot since 2026-10-01)
    n += 1
    ptype, psize = PERIOD["M1"]   # M1 host chart
    content = hdr(
        cid=base_id + n, now=now, ptype=0, psize=1,   # M1 host chart
        strat=0, tfv=1, magic=26092501, trail="false")
    content = content.replace("name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
                              "name=%s\npath=%s" % (SMVP_CHART["expert_name"],
                                                    SMVP_CHART["expert_path"]))
    single_inputs = ("InpStrategy=0\nInpTimeframe=1\nInpLots=0.01\nInpMagic=26092501\n"
                     "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                     "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50")
    if single_inputs not in content:
        raise SystemExit("chart16 template surgery failed -- aborting")
    content = content.replace(single_inputs, SMVP_CHART["inputs"])
    path = os.path.join(OUT, "chart%02d.chr" % n)
    with open(path, "w", encoding="utf-16", newline="") as f:
        f.write(content.replace("\n", "\r\n"))
    print("  chart%02d.chr  %-9s %-4s %-7s (SMVP, fixed 0.01 lot)" % (n, "smvp", "M1", "own"))

    # chart17-20: AetherFlow EA (MQL5 port of the Pine "Aether Flow" system).
    # Backtest verdicts (scripts/backtest_aetherflow.py, 30d, pessimistic):
    #   M15: confluence +$18 PF 1.19 (fixed twin); UT+hull would win but the
    #        filter blocks exactly confluence's winners -> confluence, no filter
    #   M30: UT-only trail +$73 PF 1.12 vs fixed -$62 -> run BOTH twins so the
    #        trailing-vs-fixed A/B continues; hull filter hurts on M30
    AETHER_CONFIGS = [
        # (suffix, magic, trailing, tf, trading_mode 0=UT/1=confluence, tag)
        ("aetherflow", "950001", "false", "M15", 1, "confluence"),
        ("aetherflow-T", "960001", "true", "M15", 1, "confluence"),
        ("aetherflow-M30", "950002", "false", "M30", 0, "UT-only"),
        ("aetherflow-M30-T", "960002", "true", "M30", 0, "UT-only"),
    ]
    for suffix, magic, trail, tf, mode, tag in AETHER_CONFIGS:
        n += 1
        ptype, psize = PERIOD[tf]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=TF_VALS[tf], magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=AetherFlowEA\npath=Experts\\FTTest\\AetherFlowEA.ex5")
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (TF_VALS[tf], magic, trail))
        # M30 verdict (backtest_trail_full_sweep.py 2026-10-01): the aether
        # 0.8/1.0/0.25 trail LOSES -$152/30d here; FTTest 0.2/0.5/0.10 flips it
        # to +$191. (aetherflow-H4 keeps 0.8/1.0/0.25: live values best.)
        #
        # 2026-10-02 CORRECTION (scripts/_aetherflow_m30_diag.py): the earlier
        # "aetherflow-M30 is negative in EVERY trail config" reading came from
        # grading the M30 leg on the H4 FEED. On the TRUE M30 feed (what this
        # chart actually runs) the trail is solidly POSITIVE and needs no cap:
        #   0.2/0.5/0.10 (these inputs) trail +$267 PF 1.44 win 66% (n=120)
        #   0.08/0.25/0.04        trail +$302 PF 1.55 win 69% (n=120)
        #   fixed twin            -$318 PF 0.82  (avg hold 15.4 bars)
        # M30 holds are already SHORT (avg 3.3 bars with the trail), so the
        # 12-bar time cap that rescued the H4 leg is unnecessary here -- the
        # original "M15/M30 legs exit fast" note was right.
        m30_inputs = ("InpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                      "InpTradingMode=%d\nInpMinConfluence=3\n"
                      "InpUseTrailing=%s\nInpTrailActAtr=0.2\nInpTrailDistAtr=0.5\n"
                      "InpTrailStepAtr=0.1\nInpAllowReal=false\nInpDeviationPts=50"
                      % (TF_VALS[tf], magic, mode, trail))
        aether_inputs = ("InpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpTradingMode=%d\nInpMinConfluence=3\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.8\nInpTrailDistAtr=1.0\n"
                         "InpTrailStepAtr=0.25\nInpAllowReal=false\nInpDeviationPts=50"
                         % (TF_VALS[tf], magic, mode, trail))
        if single_inputs not in content or "AetherFlowEA" not in content:
            raise SystemExit("aetherflow %s template surgery failed -- aborting"
                             % suffix)
        content = content.replace(single_inputs,
                                  m30_inputs if tf == "M30" else aether_inputs)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-18s %-4s magic %s  (AetherFlowEA %s, trailing=%s)"
              % (n, suffix, tf, magic, tag, trail))

    # chart21-24: market profile + order flow strategies (TPO value-area
    # rotation/breakout and tick-delta imbalance/absorption). Each runs as a
    # fixed/trailing twin so the trailing-vs-fixed A/B continues. Order flow
    # needs the M1 host chart (its engine buckets tick flow by minute).
    NEW_STRATS = [
        # (title, expert file stem, host tf, signal tf, magic, trailing)
        # charts 21/22 = profile (RETIRED 2026-09-30, slots still generated)
        ("profile",   "FTTest_profile",   "M15", 15,   "930008", "false"),
        ("profile-T", "FTTest_profile",   "M15", 15,   "940008", "true"),
        # charts 23/24: orderflow NEVER traded (0 signals since deploy) ->
        # REPURPOSED 2026-10-01 for the London-Fix fade (90d backtest +$140
        # PF 6.17 win 76%); magics 930009/940009 kept append-only
        ("fixfade",   "FTTest_fixfade",   "M15", 15,   "930009", "false"),
        ("fixfade-T", "FTTest_fixfade",   "M15", 15,   "940009", "true"),
    ]
    for title, stem, tf, tfv, magic, trail in NEW_STRATS:
        n += 1
        ptype, psize = PERIOD[tf]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=tfv, magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=%s\npath=Experts\\FTTest\\%s.ex5" % (stem, stem))
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (tfv, magic, trail))
        if single_inputs not in content or stem not in content:
            raise SystemExit("%s chart template surgery failed -- aborting" % title)
        # supertrend verdict (backtest_trail_full_sweep.py 2026-10-01): H1 host
        # wants 0.5/0.8/0.20 -- tighter trails bleed on the coarse H1 ATR
        if stem == "FTTest_supertrend":
            content = content.replace(
                "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50" % trail,
                "InpUseTrailing=%s\nInpTrailActAtr=0.5\nInpTrailDistAtr=0.8\n"
                "InpTrailStepAtr=0.2\nInpAllowReal=false\nInpDeviationPts=50" % trail)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        # MT5 writes .chr as UTF-16 LE with BOM and CRLF endings
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-12s %-4s magic %s  (%s.ex5, trailing=%s)"
              % (n, title, tf, magic, stem, trail))
    # chart25-28: trendpullback (H1 trend + M15 pullback) + donchian
    # (Donchian-20 on the H1 host chart). Added 2026-09-28 after the
    # backtest_new_candidates.py verdicts (trail twin: TP +$95.79 / +$47.93
    # over 30d). Trail-champion twins keep the deployed 0.3/0.7/0.15 trail.
    NEW_STRATS2 = [
        # (title, expert file stem, host tf, signal tf value, magic, trailing)
        ("trendpullback",    "FTTest_trendpullback", "M15", 15, "930010", "false"),
        ("trendpullback-T",  "FTTest_trendpullback", "M15", 15, "940010", "true"),
        ("donchian",         "FTTest_donchian",      "H1",  16385, "930011", "false"),
        ("donchian-T",       "FTTest_donchian",      "H1",  16385, "940011", "true"),
    ]
    for title, stem, tf, tfv, magic, trail in NEW_STRATS2:
        n += 1
        ptype, psize = PERIOD[tf]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=tfv, magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=%s\npath=Experts\\FTTest\\%s.ex5" % (stem, stem))
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (tfv, magic, trail))
        if single_inputs not in content or stem not in content:
            raise SystemExit("%s chart template surgery failed -- aborting" % title)
        # supertrend verdict (backtest_trail_full_sweep.py 2026-10-01): H1 host
        # wants 0.5/0.8/0.20 -- tighter trails bleed on the coarse H1 ATR
        if stem == "FTTest_supertrend":
            content = content.replace(
                "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50" % trail,
                "InpUseTrailing=%s\nInpTrailActAtr=0.5\nInpTrailDistAtr=0.8\n"
                "InpTrailStepAtr=0.2\nInpAllowReal=false\nInpDeviationPts=50" % trail)
        # 2026-10-02 trail tightening for probed families (donchian-T), AFTER
        # the surgery assertions which intentionally match the DEFAULT triple.
        content = tighten_if_probed(content, title.replace("-T", ""), trail)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        # MT5 writes .chr as UTF-16 LE with BOM and CRLF endings
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-16s %-4s magic %s  (%s.ex5, trailing=%s)"
              % (n, title, tf, magic, stem, trail))
    # chart29-33 (added 2026-09-29): trend (H1 EMA50 trend + H1 EMA9/21
    # momentum) and supres (S/R window rejection bounce) twins on the H1 host
    # chart, plus aetherflow-H4 UT-only twins on the H4 host chart (same
    # 1.0/1.2/0.3 trail params as the M15/M30 aetherflow twins).
    NEW_STRATS3 = [
        # (title, expert file stem, host tf, signal tf value, magic, trailing)
        ("trend",      "FTTest_trend",  "H1", 16385, "930012", "false"),
        # chart29 trend FIXED arm: RETIRED 2026-10-05 with user approval.
        # Worst arm in the rig: 10 trips, -$249.98, -$25.00/trip, 10% win,
        # PF 0.14. The slot is still generated so later chart numbers stay
        # stable, then deleted in RETIRED_CHARTS at the end. Its open SELL
        # was closed first (magic 930012, IOC, retcode 10009).
        # 2026-10-02: trend-T tightened to TRAIL_TIGHT (probed: +2078 -> +2675
        # over 100d, and it wins on every window slice). Handled by the
        # tighten_if_probed() call below keyed on the family name.
        ("trend-T",    "FTTest_trend",  "H1", 16385, "940012", "true"),
        # charts 31/32: supres bled in walk-forward (twin -$6.57 vs fixed
        # +$277; user kept the twins 2026-10-01) -> REPURPOSED 2026-10-01 for
        # session-VWAP reversion (90d backtest +$95 PF 1.21 win 58%); magics
        # 930013/940013 kept append-only
        ("vwaprev",    "FTTest_vwaprev", "M15", 15,   "930013", "false"),
        ("vwaprev-T",  "FTTest_vwaprev", "M15", 15,   "940013", "true"),
    ]
    for title, stem, tf, tfv, magic, trail in NEW_STRATS3:
        n += 1
        ptype, psize = PERIOD[tf]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=tfv, magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=%s\npath=Experts\\FTTest\\%s.ex5" % (stem, stem))
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (tfv, magic, trail))
        if single_inputs not in content or stem not in content:
            raise SystemExit("%s chart template surgery failed -- aborting" % title)
        # supertrend verdict (backtest_trail_full_sweep.py 2026-10-01): H1 host
        # wants 0.5/0.8/0.20 -- tighter trails bleed on the coarse H1 ATR
        if stem == "FTTest_supertrend":
            content = content.replace(
                "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50" % trail,
                "InpUseTrailing=%s\nInpTrailActAtr=0.5\nInpTrailDistAtr=0.8\n"
                "InpTrailStepAtr=0.2\nInpAllowReal=false\nInpDeviationPts=50" % trail)
        # 2026-10-02 trail tightening for the probed trend family. AFTER the
        # surgery assertions, which intentionally match the DEFAULT triple.
        # (title, not stem: the stem is FTTest_trend, the family key "trend")
        content = tighten_if_probed(content, title.replace("-T", ""), trail)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        # MT5 writes .chr as UTF-16 LE with BOM and CRLF endings
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-16s %-4s magic %s  (%s.ex5, trailing=%s)"
              % (n, title, tf, magic, stem, trail))
    # chart33: aetherflow-H4 UT-only twins (H4 host chart, UT mode 0, trail
    # params inherited from the M15/M30 aetherflow verdicts)
    AETHER_H4 = [
        ("aetherflow-H4",   "950003", "false"),
        ("aetherflow-H4-T", "960003", "true"),
    ]
    # chart33-34: AetherFlow H4 UT-only twins. InpATimeStop=12 (48h on H4):
    # uncapped H4 holds are the bleed -- 60d backtest fixed -$408 uncapped vs
    # +$97 capped, trail +$95 vs +$411 (scripts/_aetherflow_cap.py). The M15/M30
    # legs stay uncapped (they exit fast and score better that way).
    for suffix, magic, trail in AETHER_H4:
        n += 1
        ptype, psize = PERIOD["H4"]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=TF_VALS["H4"], magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=AetherFlowEA\npath=Experts\\FTTest\\AetherFlowEA.ex5")
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (TF_VALS["H4"], magic, trail))
        aether_inputs = ("InpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpTradingMode=0\nInpMinConfluence=3\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.8\nInpTrailDistAtr=1.0\n"
                         "InpTrailStepAtr=0.25\nInpATimeStop=12\n"
                         "InpAllowReal=false\nInpDeviationPts=50"
                         % (TF_VALS["H4"], magic, trail))
        if single_inputs not in content or "AetherFlowEA" not in content:
            raise SystemExit("aetherflow-H4 %s template surgery failed -- aborting"
                             % suffix)
        content = content.replace(single_inputs, aether_inputs)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-18s %-4s magic %s  (AetherFlowEA H4 UT-only, trailing=%s)"
              % (n, suffix, "H4", magic, trail))
    # chart35-36 (added 2026-09-30): supertrend (Pine ta.supertrend flip on
    # the H1 host chart; faithful port after the broken-helper fix, params
    # 5 x 2.0 from the corrected sweep: H1 90d fixed +$304 PF 1.50 /
    # trail +$255 PF 1.51) fixed/trailing twins.
    NEW_STRATS4 = [
        ("supertrend",    "FTTest_supertrend", "H1", 16385, "930014", "false"),
        ("supertrend-T",  "FTTest_supertrend", "H1", 16385, "940014", "true"),
    ]
    for title, stem, tf, tfv, magic, trail in NEW_STRATS4:
        n += 1
        ptype, psize = PERIOD[tf]
        content = hdr(
            cid=base_id + n, now=now, ptype=ptype, psize=psize,
            strat=0, tfv=tfv, magic=magic, trail=trail)
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=%s\npath=Experts\\FTTest\\%s.ex5" % (stem, stem))
        single_inputs = ("InpStrategy=0\nInpTimeframe=%s\nInpLots=0.01\nInpMagic=%s\n"
                         "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                         "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50"
                         % (tfv, magic, trail))
        if single_inputs not in content or stem not in content:
            raise SystemExit("%s chart template surgery failed -- aborting" % title)
        # supertrend verdict (backtest_trail_full_sweep.py 2026-10-01): H1 host
        # wants 0.5/0.8/0.20 -- tighter trails bleed on the coarse H1 ATR
        if stem == "FTTest_supertrend":
            content = content.replace(
                "InpUseTrailing=%s\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50" % trail,
                "InpUseTrailing=%s\nInpTrailActAtr=0.5\nInpTrailDistAtr=0.8\n"
                "InpTrailStepAtr=0.2\nInpAllowReal=false\nInpDeviationPts=50" % trail)
        # 2026-10-02 trail tightening, AFTER the surgery assertions (which
        # intentionally match the DEFAULT triple). donchian-T is probed.
        content = tighten_if_probed(content, title.replace("-T", ""), trail)
        path = os.path.join(OUT, "chart%02d.chr" % n)
        # MT5 writes .chr as UTF-16 LE with BOM and CRLF endings
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-16s %-4s magic %s  (%s.ex5, trailing=%s)"
              % (n, title, tf, magic, stem, trail))
    # RETIRED 2026-09-30 (worst PF families since session start):
    #   chart03/04 meanrev-EA (22 trades -$161.33 PF 0.19)
    #   chart21/22 profile-EA (40 trades -$189.96 PF 0.33)
    # chart25/26 trendpullback: retired by the round-2 executor 2026-10-01
    # (the VPS deleted them; the bundle must match so they cannot resurrect).
    # Slots are still GENERATED above (keeps later chart numbers stable) and
    # removed here; magics 930002/940002/930008/940008/930010/940010 stay in
    # the runner MAGICS so deals.csv history keeps logging (append-only
    # contract).
    # chart37: user's compiled LiquiditySweepH4 EA deployed as-is on the H4
    # host chart (A/B arm 1). Its magic/inputs are unknown until the first
    # trade or a settings reload reveals them; FTTest conventions are NOT
    # guaranteed (no guard inside the binary).
    n += 1
    ptype, psize = PERIOD["H4"]
    content = hdr(
        cid=base_id + n, now=now, ptype=ptype, psize=psize,
        strat=0, tfv=TF_VALS["H4"], magic=930016, trail="false")
    content = content.replace(
        "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
        "name=LiquiditySweepH4\npath=Experts\\FTTest\\LiquiditySweepH4.ex5")
    single_inputs = ("InpStrategy=0\nInpTimeframe=16388\nInpLots=0.01\n"
                     "InpMagic=930016\n"
                     "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                     "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50")
    if single_inputs not in content:
        raise SystemExit("chart37 template surgery failed -- aborting")
    # liquiditysweep A/B keeps the 0.2/0.5/0.10 trail (its own sweep verdict:
    # within $2 of best; do NOT inherit the 0.10/0.3/0.05 FTTest tighten)
    content = content.replace(
        "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
        "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50",
        "InpUseTrailing=false\nInpTrailActAtr=0.2\nInpTrailDistAtr=0.5\n"
        "InpTrailStepAtr=0.1\nInpAllowReal=false\nInpDeviationPts=50")
    path = os.path.join(OUT, "chart%02d.chr" % n)
    with open(path, "w", encoding="utf-16", newline="") as f:
        f.write(content.replace("\n", "\r\n"))
    print("  chart%02d.chr  %-18s %-4s (user binary, FTTest-format inputs)"
          % (n, "liq-sweep-bin", "H4"))

    # chart38: native port (A/B arm 2) -- FT_LIQUIDITYSWEEP, magic 930015,
    # full rig contract (guard, watchdog, logging)
    n += 1
    ptype, psize = PERIOD["H4"]
    content = hdr(
        cid=base_id + n, now=now, ptype=ptype, psize=psize,
        strat=0, tfv=TF_VALS["H4"], magic=930015, trail="false")
    content = content.replace(
        "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
        "name=FTTest_liquiditysweep\npath=Experts\\FTTest\\FTTest_liquiditysweep.ex5")
    single_inputs = ("InpStrategy=0\nInpTimeframe=16388\nInpLots=0.01\n"
                     "InpMagic=930015\n"
                     "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                     "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50")
    if single_inputs not in content:
        raise SystemExit("chart38 template surgery failed -- aborting")
    # chart38 keeps 0.2/0.5/0.10 like chart37 (see verdict note above)
    content = content.replace(
        "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
        "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50",
        "InpUseTrailing=false\nInpTrailActAtr=0.2\nInpTrailDistAtr=0.5\n"
        "InpTrailStepAtr=0.1\nInpAllowReal=false\nInpDeviationPts=50")
    path = os.path.join(OUT, "chart%02d.chr" % n)
    with open(path, "w", encoding="utf-16", newline="") as f:
        f.write(content.replace("\n", "\r\n"))
    print("  chart%02d.chr  %-18s %-4s magic 930015  (FTTest_liquiditysweep.ex5)"
          % (n, "liquiditysweep", "H4"))

    # chart39 (added 2026-10-02): dayopen -- weekday server-day-open long.
    # Backtest (M15, 180d, costs + pessimistic fills): +$796 PF 1.40 win 46%;
    # weekday-only +$788 avg +$5.32 n=148 (Monday entries are noise: +$8.41).
    # Matched-time long controls at 11:00/18:00 LOSE money -> not trend beta.
    # Fixed exit only (trail grid clearly weaker: +$170 vs +$796); single
    # instance, magic 930017. Entry fires on the core's 5s dual path inside
    # the day's first M15 bar (first tick after the daily break ~01:05).
    n += 1
    ptype, psize = PERIOD["M15"]
    content = hdr(
        cid=base_id + n, now=now, ptype=ptype, psize=psize,
        strat=0, tfv=TF_VALS["M15"], magic=930017, trail="false")
    content = content.replace(
        "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
        "name=FTTest_dayopen\npath=Experts\\FTTest\\FTTest_dayopen.ex5")
    single_inputs = ("InpStrategy=0\nInpTimeframe=15\nInpLots=0.01\n"
                     "InpMagic=930017\n"
                     "InpUseTrailing=false\nInpTrailActAtr=0.1\nInpTrailDistAtr=0.3\n"
                     "InpTrailStepAtr=0.05\nInpAllowReal=false\nInpDeviationPts=50")
    if single_inputs not in content:
        raise SystemExit("chart39 template surgery failed -- aborting")
    content = content.replace(
        single_inputs,
        single_inputs + "\nInpDOSLAtr=2.0\nInpDOTimeStop=16\nInpDOGapSkipMin=180")
    path = os.path.join(OUT, "chart%02d.chr" % n)
    with open(path, "w", encoding="utf-16", newline="") as f:
        f.write(content.replace("\n", "\r\n"))
    print("  chart%02d.chr  %-18s %-4s magic 930017  (FTTest_dayopen.ex5)"
          % (n, "dayopen", "M15"))

    # charts 40-43 (added 2026-10-05): swing -- H1 structure bias + M15/M30
    # EMA21 pullback rejection, fixed/trailing twins on each timeframe.
    # Walk-forward verdict (backtest_swing_walkforward.py, 593d span, 30d
    # windows rolled every 10d):
    #     M15 52/52 windows profitable  fixed +1262.52  trail +15016.71
    #     M30 52/52 windows profitable  fixed +3017.91  trail +10125.12
    #     H1  49/52 -> DECAYS, so H1 is deliberately NOT deployed.
    # Fixed loses to trailing on both deployed timeframes, matching the
    # pattern across the rest of the rig, so both arms ship anyway: this rig
    # exists to measure that live, and the fixed arm is the control.
    # Trail params = the TIGHT triple the backtest selected (0.05/0.15/0.02).
    # Magics 930018/940018 (M15) and 930019/940019 (M30); append-only.
    for _tf, _base, _name in (("M15", 930018, "swing"),
                              ("M30", 930019, "swing-m30")):
        for _trail in ("false", "true"):
            n += 1
            magic = _base if _trail == "false" else _base + 10000
            ptype, psize = PERIOD[_tf]
            # hdr(ta/td/ts) bakes the trail straight into the template; the
            # trailing twin gets the TIGHT triple the backtest selected, the
            # fixed twin keeps the default (its InpTrail* values are inert
            # while InpUseTrailing=false, so this changes no behaviour).
            _t = TRAIL_TIGHT if _trail == "true" else TRAIL_DEFAULT
            content = hdr(
                cid=base_id + n, now=now, ptype=ptype, psize=psize,
                strat=0, tfv=TF_VALS[_tf], magic=magic, trail=_trail,
                ta=_t[0], td=_t[1], ts=_t[2])
            content = content.replace(
                "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
                "name=FTTest_swing\npath=Experts\\FTTest\\FTTest_swing.ex5")
            for _need in ("InpMagic=%d\n" % magic,
                          "name=FTTest_swing\n",
                          "InpUseTrailing=%s\n" % _trail,
                          trail_lines(_t)):
                if _need not in content:
                    raise SystemExit(
                        "chart%02d swing template surgery failed (missing %r)"
                        " -- aborting" % (n, _need))
            path = os.path.join(OUT, "chart%02d.chr" % n)
            with open(path, "w", encoding="utf-16", newline="") as f:
                f.write(content.replace("\n", "\r\n"))
            print("  chart%02d.chr  %-18s %-4s magic %d  (FTTest_swing.ex5, "
                  "trailing=%s %s)" % (n, _name, _tf, magic, _trail,
                                       _t))

    # charts 44-45 (added 2026-10-06): sweepabs -- M15 sweep + volume
    # absorption, market entry, fixed/trailing twins, magics 930020/940020.
    # Backtest (backtest_institutional_v2.py, 200d, cost-aware): fixed -$987
    # / trail +$1087 PF 1.30 win 68% two-sided (509 buys + 566 sells -- the
    # buy branch was dead until the (close-low) fix, re-validated after).
    # Trailing twin gets TRAIL_TIGHT; fixed twin is the control.
    for _trail in ("false", "true"):
        n += 1
        _magic = 930020 if _trail == "false" else 940020
        _t = TRAIL_TIGHT if _trail == "true" else TRAIL_DEFAULT
        content = hdr(
            cid=base_id + n, now=now, ptype=PERIOD["M15"][0],
            psize=PERIOD["M15"][1],
            strat=0, tfv=TF_VALS["M15"], magic=_magic, trail=_trail,
            ta=_t[0], td=_t[1], ts=_t[2])
        content = content.replace(
            "name=FTTestEA\npath=Experts\\FTTest\\FTTestEA.ex5",
            "name=FTTest_sweepabs\npath=Experts\\FTTest\\FTTest_sweepabs.ex5")
        for _need in ("InpMagic=%d\n" % _magic,
                      "name=FTTest_sweepabs\n",
                      "InpUseTrailing=%s\n" % _trail,
                      trail_lines(_t)):
            if _need not in content:
                raise SystemExit(
                    "chart%02d sweepabs template surgery failed (missing %r)"
                    " -- aborting" % (n, _need))
        path = os.path.join(OUT, "chart%02d.chr" % n)
        with open(path, "w", encoding="utf-16", newline="") as f:
            f.write(content.replace("\n", "\r\n"))
        print("  chart%02d.chr  %-18s %-4s magic %d  (FTTest_sweepabs.ex5, "
              "trailing=%s %s)" % (n, "sweepabs", "M15", _magic, _trail,
                                   _t))

    # 2026-10-06: vwaprev (charts 31/32) UN-RETIRED -- the live -52.39 came
    # from 6 trips (noise); the 200d cost-aware backtest says +402.68 over
    # 301 trips PF 1.19. Re-forward-test, not vindication: the rows were
    # always generated above, only the deletion list changes.
    RETIRED_CHARTS = (3, 4, 21, 22, 25, 26, 29, 2, 5, 13, 14, 17, 27, 28,
33, 34, 35, 36)
    for rc in RETIRED_CHARTS:
        p = os.path.join(OUT, "chart%02d.chr" % rc)
        if os.path.exists(p):
            os.remove(p)
            print("  chart%02d.chr  REMOVED (retired)" % rc)
    print("wrote %d charts to %s (retired slots deleted: %s)"
          % (n, OUT, ",".join(str(c) for c in RETIRED_CHARTS)))


if __name__ == "__main__":
    main()
