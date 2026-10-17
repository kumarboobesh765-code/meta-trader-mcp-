"""One-off: measure MT5 bar-label offset vs real UTC.

Compares (a) the newest M15 bar's OPEN time label, (b) the newest tick time,
and (c) real UTC now. The bar covering 'now' tells us how far labels are
shifted from UTC. Also prints today's bar-time hour histogram to locate the
daily break (hours with missing bars).
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import MetaTrader5 as mt5
from forward_test import load_env, closed_bars
from datetime import datetime, timezone

load_env()
assert mt5.initialize(), mt5.last_error()
tick = mt5.symbol_info_tick("XAUUSD")
now_utc = datetime.now(timezone.utc)
bars = closed_bars("XAUUSD", "M15", 3)
last = bars[-1] if bars else None
print("real UTC now      :", now_utc.strftime("%Y-%m-%d %H:%M:%S"))
print("epoch now         :", int(now_utc.timestamp()))
print("newest tick time  :", datetime.fromtimestamp(tick.time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "(labeled as UTC)")
print("last closed bar   :", datetime.fromtimestamp(last["time"], timezone.utc).strftime("%Y-%m-%d %H:%M") if last else "-")
print("bar open label    :", last["time"])
print("now - barlabel    : %.1f min" % ((now_utc.timestamp() - last["time"]) / 60.0))
# which labeled-hour does the LIVE moment fall in vs bar-label hour?
print("live UTC hour     :", now_utc.hour, "| newest-bar label hour:", datetime.fromtimestamp(last["time"], timezone.utc).hour)
mt5.shutdown()
