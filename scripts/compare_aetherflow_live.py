r"""Compare LIVE aetherflow twin fills vs backtest expectations. Runs ON THE VPS.

The rig runs four AetherFlow streams on XAUUSD:
  950001 aetherflow      M15 confluence, fixed SL
  960001 aetherflow-T    M15 confluence, trailing SL
  950002 aetherflow-M30    M30 UT-only, fixed SL
  960002 aetherflow-M30-T  M30 UT-only, trailing SL

Backtest expectations (scripts/backtest_aetherflow.py):
  M15 confluence 30d: fixed +$18.18 PF 1.19 / trail +$11.68  -> fixed favored
  M30 UT-only   30d: fixed -$62.10 / trail +$73.11 PF 1.12   -> trail favored
  M30 UT-only   90d: fixed -$272 / trail -$209 (both lose; trail still beats
                fixed RELATIVELY by ~$64) -> relative A/B is the live question

This tool groups the account's deals into round trips per magic since the
given date and reports, per stream: trades, net, win rate, PF -- then the
head-to-head verdict (trail twin vs fixed twin) against the expectation.

Usage:  python compare_aetherflow_live.py [--since YYYY-MM-DD] [--tg]
        (default --since: the deployment date 2026-09-29; --tg sends the
         same report to Telegram -- used by the weekly scheduled task)
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
DEFAULT_SINCE = "2026-09-29"   # charts 19/20 went live after the 17:01 reboot

STREAMS = {
    950001: ("aetherflow M15 confluence", "fixed"),
    960001: ("aetherflow-T M15 confluence", "trail"),
    950002: ("aetherflow-M30 UT", "fixed"),
    960002: ("aetherflow-M30-T UT", "trail"),
}


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


def round_trips(deals, magic):
    """Group in+out deals of one magic into closed round trips."""
    opens = {}
    trips = []
    for d in deals:
        if d.magic != magic:
            continue
        if d.entry == mt5.DEAL_ENTRY_IN:
            opens[d.position_id] = d
        elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            o = opens.pop(d.position_id, None)
            trips.append({
                "time": d.time,
                "profit": d.profit + d.commission + d.swap
                          + (o.commission if o else 0.0),
                "volume": d.volume,
            })
    return trips


def stats(trips):
    if not trips:
        return None
    net = sum(t["profit"] for t in trips)
    wins = [t for t in trips if t["profit"] > 0]
    losses = [t for t in trips if t["profit"] <= 0]
    gw = sum(t["profit"] for t in wins)
    gl = abs(sum(t["profit"] for t in losses))
    pf = (gw / gl) if gl > 0 else float("inf")
    return {"n": len(trips), "net": net,
            "winrate": 100.0 * len(wins) / len(trips), "pf": pf}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--tg", action="store_true",
                    help="also send the report via Telegram")
    args = ap.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp()

    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    try:
        deals = mt5.history_deals_get(since, datetime.now(
            timezone.utc).timestamp() + 4 * 3600) or []
    finally:
        mt5.shutdown()

    report = ["AetherFlow live-vs-backtest (since %s, %d deals scanned)"
              % (args.since, len(deals))]
    st = {}
    for magic in (950001, 960001, 950002, 960002):
        s = stats(round_trips(deals, magic))
        st[magic] = s
        name, style = STREAMS[magic]
        if s is None:
            report.append("  %-26s (%s)  no closed trades yet" % (name, style))
        else:
            report.append("  %-26s (%s)  n=%d  net=%+.2f  win=%.0f%%  PF=%s"
                          % (name, style, s["n"], s["net"], s["winrate"],
                             ("%.2f" % s["pf"]) if s["pf"] != float("inf")
                             else "inf"))

    def pair(base, twin, expect):
        f, t = st.get(base), st.get(twin)
        if f is None or t is None:
            report.append("  %s: not enough data yet" % expect["label"])
            return
        diff = t["net"] - f["net"]
        verdict = ("TRAIL outperformed by %+.2f (expected)" % diff) \
            if diff > 0 else ("FIXED outperformed by %+.2f (against expectation)"
                              % -diff)
        report.append("  %s: trail-fixed diff %+.2f -> %s"
                      % (expect["label"], diff, verdict))

    report.append("head-to-head:")
    pair(950002, 960002, {"label": "M30 UT (backtest: trail favored)"})
    pair(950001, 960001, {"label": "M15 confluence (backtest: fixed favored)"})

    text = "\n".join(report)
    print(text)
    if args.tg:
        send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
