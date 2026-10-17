"""Verify the two anomalous magic-0 XAUUSD deals from 2026-09-28 05:55.

They closed +$181.21 and +$184.77 six seconds apart on 0.01 lots. On XAUUSD
0.01 lot == 1 oz, so a $181 profit needs a ~$181 price move inside six seconds,
which is not a thing gold does. Together they are +$366 of a +$512 total net,
so if they are bad fills the whole era result inverts. Print every deal on those
position_ids (entry + exit) with prices, plus the surrounding XAUUSD quotes we
can get from the journal-era tick range.
"""
import datetime as dt
import time

import MetaTrader5 as mt5

TARGETS = {2049566821, 2049570241}


def ts(t):
    return dt.datetime.fromtimestamp(int(t), dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

print("=== every deal on the two suspicious position_ids ===")
for d in mt5.history_deals_get(0, int(time.time())):
    if d.position_id not in TARGETS:
        continue
    kind = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}.get(d.entry, str(d.entry))
    print("  %s  pid=%d %-6s %-6s %-7s vol=%.2f price=%.2f  pnl=%+9.2f comm=%+.2f swap=%+.2f"
          % (ts(d.time), d.position_id, kind,
             "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
             d.symbol, d.volume, d.price, d.profit, d.commission, d.swap))

print("\n=== all XAUUSD magic-0 deals on 09-28, for price context ===")
for d in mt5.history_deals_get(0, int(time.time())):
    if d.magic != 0 or d.symbol != "XAUUSD":
        continue
    if not d.time:
        continue
    day = ts(d.time)[:10]
    if day != "2026-09-28":
        continue
    kind = {0: "IN", 1: "OUT"}.get(d.entry, str(d.entry))
    print("  %s  pid=%d %-3s %-4s vol=%.2f price=%.2f pnl=%+9.2f"
          % (ts(d.time), d.position_id, kind,
             "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
             d.volume, d.price, d.profit))

mt5.shutdown()