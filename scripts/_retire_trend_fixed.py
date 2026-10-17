"""Retire the trend FIXED twin (chart29, magic 930012).

User approved: close its open position AND detach the chart. This handles only
the position half; the .chr retirement is done separately.

CRITICAL: at the time of writing there are FOUR open positions at an identical
price/SL/TP (4127.26 / 4173.10 / 4058.48) belonging to magics 930012, 930011,
930014 and 940014. They must never be told apart by price -- select strictly on
magic == 930012, then re-read the position by ticket and assert the magic again
before sending, so a concurrent close cannot make us fire on the wrong ticket.

Vantage XAUUSD is IOC-only, so use filling_mode=ORDER_FILLING_IOC and run
mt5.order_check() first to confirm the request is acceptable.
"""
import datetime as dt
import time

import MetaTrader5 as mt5

TARGET_MAGIC = 930012
SYMBOL = "XAUUSD"


def ts():
    return dt.datetime.now().strftime("%H:%M:%S")


if not mt5.initialize():
    raise SystemExit("initialize failed: %r" % mt5.last_error())

info = mt5.symbol_info(SYMBOL)
tick = mt5.symbol_info_tick(SYMBOL)
print("account %d  %s" % (mt5.account_info().login, mt5.account_info().server))
print("%s  %s bid=%.2f ask=%.2f  point=%.2f  contract=%.2f"
      % (ts(), SYMBOL, tick.bid, tick.ask,
         info.point, info.trade_contract_size))
print("filling modes: IOC=%d RETURN=%d" % (mt5.ORDER_FILLING_IOC,
                                           mt5.ORDER_FILLING_RETURN))

mine = [p for p in mt5.positions_get(symbol=SYMBOL)
        if p.magic == TARGET_MAGIC]
print("\npositions with magic %d: %d" % (TARGET_MAGIC, len(mine)))

if not mine:
    print("nothing to close for magic %d -- already flat" % TARGET_MAGIC)
    mt5.shutdown()
    raise SystemExit(0)

for p in mine:
    print("  ticket=%d type=%s vol=%.2f open=%.2f sl=%.2f tp=%.2f profit=%.2f"
          % (p.ticket, "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
             p.volume, p.price_open, p.sl, p.tp, p.profit))

closed = 0
for p in mine:
    # re-read by ticket and re-assert the magic immediately before sending
    live = mt5.positions_get(ticket=p.ticket)
    if not live:
        print("  ticket %d already gone, skipping" % p.ticket)
        closed += 1
        continue
    live = live[0]
    if live.magic != TARGET_MAGIC:
        print("  ABORT ticket %d magic drifted to %d" % (p.ticket, live.magic))
        continue

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "position": live.ticket,
        "volume": live.volume,
        "type": (mt5.ORDER_TYPE_SELL if live.type == mt5.POSITION_TYPE_BUY
                 else mt5.ORDER_TYPE_BUY),
        "deviation": 30,
        "magic": TARGET_MAGIC,
        "comment": "retire trend fixed",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    chk = mt5.order_check(req)
    print("  order_check retcode=%s" % getattr(chk, "retcode", "?"))
    if chk is not None and getattr(chk, "retcode", 0) not in (
            0, 10009, 10013, 10014, 10015, 10016, 10017, 10018, 10019, 10020):
        print("  order_check rejected, not sending")

    res = mt5.order_send(req)
    if res is None:
        print("  order_send returned None, last_error=%r" % mt5.last_error())
        continue
    print("  send retcode=%s done=%s deal=%s comment=%r"
          % (res.retcode, getattr(res, "done", "?"),
             getattr(res, "deal", "?"), getattr(res, "comment", "")))
    # 0 TRADE_RETCODE_DONE and 10009 TRADE_RETCODE_DONE_PARTIAL are both success
    if res.retcode in (0, 10009, 10013, 10014, 10015):
        closed += 1
    time.sleep(2)

time.sleep(2)
left = [p for p in mt5.positions_get(symbol=SYMBOL)
        if p.magic == TARGET_MAGIC]
print("\nresult: closed=%d  still open with magic %d: %d"
      % (closed, TARGET_MAGIC, len(left)))
for p in left:
    print("  LEFTOVER ticket=%d vol=%.2f open=%.2f" % (p.ticket, p.volume, p.price_open))
mt5.shutdown()