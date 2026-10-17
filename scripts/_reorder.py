"""One-shot: delete and re-place all forward-test orders so the MT5 'Comment'
column shows the strategy name ('breakout 910001' style).

- Positions (magic 9100xx): closed and re-opened same direction, same SL/TP.
- Pending orders: deleted (the forward-test runner re-places its straddle stops
  with labeled comments on restart).

Stop the runner (taskkill) before running this, then restart it.

Usage: python scripts/_reorder.py
"""

import os
import subprocess
import sys
import time

import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forward_test import MAGICS, VOLUME, filling_mode, label, round_price

out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout.lower()
if "terminal64.exe" not in out and "terminal.exe" not in out:
    print("MT5 not running -- open it manually first.")
    raise SystemExit(1)

if not mt5.initialize():
    print("mt5.initialize() failed:", mt5.last_error())
    raise SystemExit(1)

acc = mt5.account_info()
if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
    print("REFUSING: not a demo account.")
    mt5.shutdown()
    raise SystemExit(1)

# find the symbol traded by our positions/orders
tickets = [p.symbol for p in (mt5.positions_get() or []) if p.magic in MAGICS]
tickets += [o.symbol for o in (mt5.orders_get() or []) if o.magic in MAGICS]
symbol = tickets[0] if tickets else "XAUUSD"
print("symbol:", symbol)

# 1) delete ALL pending orders with our magic numbers
for o in (mt5.orders_get(symbol=symbol) or []):
    if o.magic not in MAGICS:
        continue
    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    print("deleted pending #%d %s" % (o.ticket, "ok" if ok else
          "FAILED retcode=%s" % (res.retcode if res else "none")))
    time.sleep(0.3)

# 2) close and re-open each labeled position with the strategy label in comment
for p in (mt5.positions_get(symbol=symbol) or []):
    if p.magic not in MAGICS:
        continue
    side = "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell"
    close_type = mt5.ORDER_TYPE_SELL if side == "buy" else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = round_price(symbol, tick.bid if side == "buy" else tick.ask)
    res = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": p.volume,
        "type": close_type, "position": p.ticket, "price": price,
        "deviation": 50, "magic": p.magic, "comment": label(p.magic) + " close",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_mode(symbol),
    })
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    print("closed #%d %s" % (p.ticket, "ok" if ok else
          "FAILED retcode=%s" % (res.retcode if res else "none")))
    if not ok:
        continue
    time.sleep(0.3)
    tick = mt5.symbol_info_tick(symbol)
    price = round_price(symbol, tick.ask if side == "buy" else tick.bid)
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": p.volume,
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price, "deviation": 50, "magic": p.magic,
        "comment": label(p.magic),
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_mode(symbol),
    }
    if p.sl:
        req["sl"] = round_price(symbol, p.sl)
    if p.tp:
        req["tp"] = round_price(symbol, p.tp)
    res = mt5.order_send(req)
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    print("reopened %s %s comment=%r %s" % (label(p.magic), side.upper(), label(p.magic),
          "ok @ %.2f" % res.price if ok else
          "FAILED retcode=%s" % (res.retcode if res else "none")))
    time.sleep(0.3)

print("\nfinal state:")
for p in (mt5.positions_get() or []):
    print("  POS  #%d magic=%d %s comment=%r" % (p.ticket, p.magic,
          "BUY" if p.type == 0 else "SELL", p.comment))
for o in (mt5.orders_get() or []):
    print("  ORD  #%d magic=%d @ %.2f comment=%r" % (o.ticket, o.magic, o.price_open, o.comment))
if not (mt5.positions_get() or []) and not (mt5.orders_get() or []):
    print("  (none)")
mt5.shutdown()
