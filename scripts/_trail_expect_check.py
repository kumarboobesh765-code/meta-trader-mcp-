r"""Daily: live trailing results vs the sweep's per-trip expectations.

Answers (2026-10-01 request): "tomorrow, compare live trailing results
against the sweep's expectations and flag any family underperforming its
backtest."

Expectations = avg $/trip from the 2026-10-01 trail sweep (30d) for the
DEPLOYED config; families the sweep could not test use the walk-forward
(11x14d) trail-twin averages. Flags:
  UNDERPERF  >= 4 live trips and live avg/trip < 0 while expectation > 0
  NEG-EXPECT trading a family whose walk-forward trail average is negative
             (supres-T: fixed dominates every trail config)
  NOTRADE    expectation > +$2/trip and zero trips 72h after deploy (only
             fires when the script is run >= 72h after DEPLOY_TS)

Usage: python _trail_expect_check.py [--json C:/FTTest/logs/trail_expect.json]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from champion_check import send_telegram, streams
from forward_test import load_env

# families outside champion_check.streams(): aetherflow twins + the
# liquiditysweep A/B arms tracked SEPARATELY (930015 port, 930016 binary).
# The binary's expectation is 0.0 (unknown until it trades) so it is
# monitor-only: no UNDERPERF/NOTRADE flags can fire on it.
EXTRA_STREAMS = [
    ("XAUUSD", "aetherflow-M30", 950002, 960002, "trail"),
    ("XAUUSD", "aetherflow-H4", 950003, 960003, "trail"),
    ("XAUUSD", "liquiditysweep-port", 930015, 930015, "trail"),
    ("XAUUSD", "liquiditysweep-BIN", 930016, 930016, "trail"),
]

DEPLOY_TS = datetime(2026, 10, 1, 12, 35, tzinfo=timezone.utc)

# avg $/trip for the DEPLOYED trail config -- trail sweep 2026-10-01 (30d),
# walk-forward 11x14d for donchian/trend. Retired families (meanrev,
# trendpullback, supres) removed 2026-10-01. fixfade/vwaprev expectations
# come from backtest_institutional.py (2026-10-01): fixfade +$3.03/trip
# (140.15/46, 90d), vwaprev +$1.11/trip (95.17/86, 90d).
# trend 3.49 = state-machine walk-forward (scripts/_trend_state_bt.py,
# 2026-10-02): live-parity engine (exit-bar re-entries + reversals, rolling
# ATR) +$3581/1026 trips, 11/11 windows positive. The old 3.84 came from the
# busy-lock engine, which skips exactly the whipsaw re-entries the live EA
# takes and so overstates the edge in chop.
EXPECT_AVG = {
    # 2026-10-02: the five TRAIL_TIGHT families were moved from
    # 0.10/0.3/0.05 to 0.05/0.15/0.02 (see TRAIL_TIGHT in
    # make_ea_profile.py). Their per-trip expectations are re-derived from the
    # tightening sweep at the DEPLOYED triple (100d, $0.24/trade, pessimistic
    # fills, scripts/_trail_tighter_sweep.py): net/n at 0.05/0.15/0.02.
    "breakout": 3.05,   # +1946.90 / 639
    "macross": 4.91,   # +859.16 / 175
    "smc": 2.05,   # +588.10 / 287
    "squeeze": 4.21,   # +855.60 / 203
    # trend: MEASURED, not assumed (scripts/_trend_state_tight.py). The
    # live-parity state machine (re-entries, no exit-bar signal skip) at the
    # DEPLOYED 0.05/0.15/0.02 triple over the same 11x14d walk-forward the
    # other values came from: +5722.46 / 1101 trips = +5.20/trip. The
    # walk/state ratio was re-measured per triple (2.27 at the tight trail,
    # NOT the 0.91 haircut guessed from the old trail), so no borrowed factor.
    # Corroborated on the exact live window: old trail -$23 (PF 0.72) ->
    # new trail +$32 (PF 1.44, win 79%).
    "trend": 5.20,
    # donchian moved to TRAIL_TIGHT on 2026-10-02: +1111/169 = +6.57/trip
    # (scripts/_trail_untested_families.py, 100d + 5/5 windows). It was
    # untested at the old triple, so this is its first tight-trail number.
    "donchian": 6.57,
    "fixfade": 3.03, "vwaprev": 1.11,
    "aetherflow-M30": 2.58,
    # aetherflow-H4 8.16 was the UNCAPPED sweep (60d sweep UT). The H4 legs
    # now carry a 12-bar (48h) time stop (InpATimeStop=12, charts 33/34);
    # capped 60d: fixed +$97/24 trips, trail +$411/27 trips -> keep the old
    # value conservative rather than re-derive (live trips will decide).
    "aetherflow-H4": 8.16, "supertrend": 2.54,
    "liquiditysweep-port": 9.11, "liquiditysweep-BIN": 0.0,
    # dayopen deployed 2026-10-02 (backtest +$5.32/trip weekday). Monitor-only
    # (0.0) until it has live trips: its first possible entry is Mon 22:05 UTC
    # (the weekend-gap Sunday open is skipped by design), so a real
    # expectation would trip NOTRADE 72h after the trail DEPLOY_TS.
    "dayopen": 0.0,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    load_env()
    ok = False
    for attempt in range(3):
        if mt5.initialize():
            ok = True
            break
        mt5.shutdown()
        time.sleep(5)
    if not ok:
        print("mt5.initialize failed")
        return 1

    frm = datetime.now(timezone.utc) - timedelta(days=3)
    deals = mt5.history_deals_get(frm, datetime.now(timezone.utc) + timedelta(days=1))
    mt5.shutdown()
    # only deals closed AFTER the trail deploy -- otherwise the first days
    # report pre-tighten bleed as UNDERPERF (meaningless)
    dep_epoch = int(DEPLOY_TS.timestamp())
    deals = [d for d in (deals or []) if d.time >= dep_epoch]
    if not deals:
        print("no post-deploy deals yet (deployed %s) -- nothing to grade"
              % DEPLOY_TS.strftime("%m-%d %H:%M"))
        return 0

    rows, flags = [], []
    for sym, name, base_m, twin_m, champ in list(streams()) + EXTRA_STREAMS:
        if name not in EXPECT_AVG:
            continue
        outs = [d for d in deals
                if d.magic == twin_m and d.entry in (mt5.DEAL_ENTRY_OUT,
                                                     mt5.DEAL_ENTRY_INOUT)]
        net = sum(d.profit + d.swap + d.commission for d in outs)
        n = len(outs)
        exp = EXPECT_AVG[name]
        status = "ok"
        if n >= 4 and exp > 0 and net / n < 0:
            status = "UNDERPERF"
            flags.append("%s: %d trips avg %+.2f vs expect +%.2f"
                         % (name, n, net / n, exp))
        elif exp < 0 and n > 0:
            status = "NEG-EXPECT"
            flags.append("%s: trading a trail arm whose backtest avg is "
                         "negative (%+.2f/trip) -- retire candidate" % (name, exp))
        elif n == 0 and exp > 2.0 and \
                datetime.now(timezone.utc) - DEPLOY_TS > timedelta(hours=72):
            status = "NOTRADE"
            flags.append("%s: 0 trips 72h+ after trail deploy (expect +%.2f/trip)"
                         % (name, exp))
        rows.append({"name": name, "trips": n, "net": round(net, 2),
                     "expect_avg": exp, "status": status})
        print("  %-18s %3d trips %+8.2f  expect +%.2f/trip  %s"
              % (name, n, net, exp, status))

    print("VERDICT: %d flags (post-deploy deals only)" % len(flags))
    for f in flags:
        print("  FLAG " + f)
    if flags:
        try:
            send_telegram("FTTrailExpect: " + " | ".join(flags))
        except Exception as e:
            print("telegram send failed: %s" % e)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"ts": time.time(), "rows": rows, "flags": flags},
                      fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
