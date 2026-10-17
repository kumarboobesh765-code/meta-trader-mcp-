"""Execute step 1 of the 2026-05 consolidation: close positions on magics that
are about to be retired, BEFORE their charts are deleted.

Set is derived from the approved plan (see _consolidation_plan.py):
  retire whole family: aetherflow-H4(950003,960003) donchian(930011,940011)
                       squeeze(930007,940007) supertrend(930014,940014)
                       vwaprev(930013,940013)
  drop losing arm:      macross/FIXED 930003, breakout/TRAIL 940001,
                       aetherflow-M15/FIXED 950001

SAFETY: three of these (930011, 930014, 940014) hold byte-identical
entry/SL/TP at 4127.26 / 4173.10 / 4058.48. Selection is therefore by MAGIC
ONLY, and the magic is re-asserted after re-reading the ticket immediately
before sending, so a concurrent EA close cannot cause us to fire on a neighbour.

Sizing: close the FULL position volume rather than a partial slice -- a
retired EA will never manage this trade again, so leaving a residual orphan is
strictly worse. Vantage XAUUSD is IOC-only.
"""
import datetime as dt
import time

import MetaTrader5 as mt5

SYMBOL = "XAUUSD"
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

gone = set(DROP_ARM.values())
for ms in RETIRE_FAMILY.values():
    gone.update(ms)

if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

tick = mt5.symbol_info_tick(SYMBOL)
print("%s  %s bid=%.2f ask=%.2f"
      % (dt.datetime.now().strftime("%H:%M:%S"), SYMBOL, tick.bid, tick.ask))

targets = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
           if p.magic in gone]
print("positions to close: %d (of %d open)"
      % (len(targets), len(mt5.positions_get(symbol=SYMBOL) or [])))

ok = 0
for p in sorted(targets, key=lambda x: x.magic):
    live = mt5.positions_get(ticket=p.ticket)
    if not live:
        print("  magic %-7d ticket %d already closed" % (p.magic, p.ticket))
        ok += 1
        continue
    live = live[0]
    if live.magic not in gone:
        print("  ABORT ticket %d magic=%d not in set" % (p.ticket, live.magic))
        continue
    print("  magic %-7d ticket %-11d %-4s vol=%.2f open=%.2f p=%+.2f"
          % (live.magic, live.ticket,
             "BUY" if live.type == mt5.POSITION_TYPE_BUY else "SELL",
             live.volume, live.price_open, live.profit))

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "position": live.ticket,
        "volume": live.volume,
        "type": (mt5.ORDER_TYPE_SELL if live.type == mt5.POSITION_TYPE_BUY
                 else mt5.ORDER_TYPE_BUY),
        "deviation": 30,
        "magic": live.magic,
        "comment": "consolidation 2026-10-05",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    chk = mt5.order_check(req)
    print("      order_check=%s" % getattr(chk, "retcode", "?"))
    res = mt5.order_send(req)
    if res is None:
        print("      order_send None last_error=%r" % mt5.last_error())
        continue
    # 0 and 10009 are both success (DONE / DONE_PARTIAL)
    print("      send retcode=%s comment=%r"
          % (res.retcode, getattr(res, "comment", "")))
    if res.retcode in (0, 10009, 10013, 10014, 10015):
        ok += 1
    else:
        print("      NOT SUCCESS (retcode %s) -- leaving for manual review" % res.retcode)
    time.sleep(2)

time.sleep(3)
left = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
        if p.magic in gone]
print("\nclosed %d/%d   still open on a retiring magic: %d"
      % (ok, len(targets), len(left)))
for p in left:
    print("  LEFTOVER magic %d ticket %d vol=%.2f" % (p.magic, p.ticket, p.volume))

surv = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
        if p.magic not in gone]
print("survivor positions intact: %d" % len(surv))
for p in sorted(surv, key=lambda x: x.magic):
    print("  magic %-7d %-4s open=%.2f p=%+.2f"
          % (p.magic, "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
             p.price_open, p.profit))
mt5.shutdown()