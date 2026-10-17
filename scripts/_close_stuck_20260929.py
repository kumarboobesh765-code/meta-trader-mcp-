"""Close the 3 stuck SELL positions by ticket (server lagging, price through stop).
Keeps EA magic on the closing deal so stats attribute to the right family. Retries."""
from datetime import datetime, timezone

import MetaTrader5 as mt5

TICKETS = [2103956425, 2103956435, 2104175793]
SYMBOL = "XAUUSD"

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    raise SystemExit(1)

mt5.symbol_select(SYMBOL, True)


def close_one(ticket):
    for attempt in range(6):
        poss = mt5.positions_get(ticket=ticket)
        if not poss:
            print(f"  #{ticket} already closed")
            return True
        p = poss[0]
        tick = mt5.symbol_info_tick(SYMBOL)
        is_buy_pos = p.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": SYMBOL,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_BUY if not is_buy_pos else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if not is_buy_pos else tick.bid,
            "deviation": 300,
            "magic": p.magic,
            "comment": "manual-unstick",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        rc = r.retcode if r else None
        if rc in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, mt5.TRADE_RETCODE_PLACED):
            print(f"  #{ticket} closed at {req['price']} (magic {p.magic}, pnl was {p.profit:+.2f}) "
                  f"attempt {attempt + 1}")
            return True
        print(f"  #{ticket} attempt {attempt + 1} retcode={rc} ({r.comment if r else 'no reply'}); "
              f"price now {tick.bid}/{tick.ask}; retrying in 10s")
        import time
        time.sleep(10)
    print(f"  #{ticket} FAILED after 6 attempts")
    return False


print(f"=== closing stuck sells {datetime.now(timezone.utc):%H:%M:%S}Z ===")
results = {t: close_one(t) for t in TICKETS}
left = mt5.positions_get(ticket=TICKETS[0]) or []
for t in TICKETS:
    if mt5.positions_get(ticket=t):
        print(f"  STILL OPEN: #{t}")
    else:
        print(f"  confirmed closed: #{t}")
mt5.shutdown()
print("done:", results)
