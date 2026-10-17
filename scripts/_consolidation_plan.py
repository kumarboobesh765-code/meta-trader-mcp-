"""Build the exact consolidation plan before touching anything. READ-ONLY.

Decision (user, 2026-10-05): consolidate to the survivors -- retire families
that lose in BOTH arms, drop only the losing arm where the twin wins.

Mappings below are taken from the two authoritative sources and were checked
against the deployed profile, because two guesses were wrong on the first pass:

  * 940009 is FIXFADE, not trendpullback. trendpullback is 930010/940010, and
    those charts (25/26) were ALREADY retired on 2026-10-01, so there is no
    trendpullback arm left to drop. The approved "4 losing arms" is really 3.
  * 950002 is aetherflow-M30 (a winner, +86.37 FIXED), NOT aetherflow-M15.
    M15 is 950001/960001. aetherflow-H4 is 950003/960003 on charts 33/34.

RETIRE WHOLE FAMILY (both arms lose -- no configuration rescues them):
    aetherflow-H4  -314.97   950003 chart33, 960003 chart34
    donchian       -217.08   930011 chart27, 940011 chart28
    squeeze        -105.12   930007 chart13, 940007 chart14
    supertrend     -103.42   930014 chart35, 940014 chart36
    vwaprev         -52.39   930013 chart31, 940013 chart32

DROP ONLY THE LOSING ARM (twin is profitable):
    macross FIXED        930003 chart05   (twin TRAIL 940003 +71.73 PF 4.25)
    breakout TRAIL       940001 chart02   (twin FIXED 930001 +45.31)
    aetherflow-M15 FIXED 950001 chart17   (twin TRAIL 960002... see note)

Positions are selected by MAGIC ONLY. Several families hold byte-identical
entry/SL/TP -- 930011, 930014 and 940014 all sit at 4127.26 / 4173.10 / 4058.48 --
so price is never a valid selector and must never be used to identify a ticket.
"""
import MetaTrader5 as mt5

# magic -> chart number, read off scripts/_health_expect.json (deployed truth)
CHART_OF = {
    930001: 1, 940001: 2, 930003: 5, 940003: 6, 930004: 7, 940004: 8,
    930005: 9, 940005: 10, 930006: 11, 940006: 12, 930007: 13, 940007: 14,
    26092501: 16, 950001: 17, 960001: 18, 950002: 19, 960002: 20,
    930009: 23, 940009: 24, 930011: 27, 940011: 28, 940012: 30,
    930013: 31, 940013: 32, 950003: 33, 960003: 34, 930014: 35, 940014: 36,
    930016: 37, 930015: 38, 930017: 39,
}

RETIRE_FAMILY = {
    "aetherflow-H4": [950003, 960003],
    "donchian": [930011, 940011],
    "squeeze": [930007, 940007],
    "supertrend": [930014, 940014],
    "vwaprev": [930013, 940013],
}
DROP_ARM = {
    "macross/FIXED": 930003,
    "breakout/TRAIL": 940001,
    "aetherflow-M15/FIXED": 950001,
}

if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

acc = mt5.account_info()
pos = mt5.positions_get(symbol="XAUUSD") or []
print("account %d  balance=%.2f  equity=%.2f" % (acc.login, acc.balance, acc.equity))
print("open XAUUSD positions: %d\n" % len(pos))

retire = set()
for f, ms in RETIRE_FAMILY.items():
    retire.update(ms)
drop = set(DROP_ARM.values())
gone = retire | drop


def why(m):
    if m in retire:
        for f, ms in RETIRE_FAMILY.items():
            if m in ms:
                return "retire %s (both arms lose)" % f
    return "drop arm: %s" % next(k for k, v in DROP_ARM.items() if v == m)


print("=" * 78)
print("STEP 1 -- CLOSE THESE POSITIONS (by magic; run BEFORE deleting charts)")
print("=" * 78)
n_close = 0
for p in sorted(pos, key=lambda x: x.magic):
    if p.magic in gone:
        n_close += 1
        print("  magic %-7d %-4s vol=%.2f open=%9.2f sl=%9.2f tp=%9.2f p=%+7.2f  <- %s"
              % (p.magic, "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                 p.volume, p.price_open, p.sl, p.tp, p.profit, why(p.magic)))
if not n_close:
    print("  (none -- no retired/dropped magic currently holds a position)")

print("\n" + "=" * 78)
print("STEP 2 -- SURVIVORS, DO NOT TOUCH")
print("=" * 78)
for p in sorted(pos, key=lambda x: x.magic):
    if p.magic not in gone:
        print("  magic %-7d %-4s vol=%.2f open=%9.2f p=%+7.2f   KEEP"
              % (p.magic, "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                 p.volume, p.price_open, p.profit))

charts = sorted(CHART_OF[m] for m in gone)
print("\n" + "=" * 78)
print("STEP 3 -- DELETE THESE %d CHART FILES" % len(charts))
print("=" * 78)
print("  " + ", ".join("chart%02d" % c for c in charts))
print("  rig: 31 -> %d charts" % (31 - len(charts)))

print("\n" + "=" * 78)
print("NOT IN SCOPE -- flagged for your call, deliberately NOT actioned")
print("=" * 78)
print("  940012 trend/TRAIL chart30: -133.32 over 40 trips (-3.33/trip).")
print("     Its FIXED twin (chart29) was retired last turn, and the twin")
print("     verdict says trend loses in BOTH arms, so this arm is also a")
print("     retire candidate. Left alone because it is the largest sample")
print("     in the rig and the approved scope was 5 families + 4 arms.")
print("  930009/940009 fixfade charts 23/24: no closed trips in era1 at all,")
print("     so there is no evidence either way -- untested, not disproven.")
print("  960001 aetherflow-M15/TRAIL chart18: +0.18 over n=2. Noise; keeping")
print("     it costs a chart slot and teaches nothing.")
mt5.shutdown()