"""List every live order (pending + position) on the VPS account.

Used to confirm the DeleteMyPendings() OrderDelete(0) bug is not currently
leaving orphan pending orders on the book. READ-ONLY.

Run: python C:\\FTTest\\scripts\\_health_pendings.py
"""
import sys

sys.path.insert(0, r"C:\FTTest\scripts")
import MetaTrader5 as mt5

if not mt5.initialize():
    print("mt5.initialize failed:", mt5.last_error())
    raise SystemExit(1)

ords = mt5.orders_get(symbol="XAUUSD")
if not ords:
    print("no live orders on XAUUSD (no orphan pendings)")
else:
    si = mt5.symbol_info("XAUUSD")
    dg = si.digits if si else 2
    TYPES = {0: "BUY", 1: "SELL", 2: "BUY_LIMIT", 3: "SELL_LIMIT",
             4: "BUY_STOP", 5: "SELL_STOP"}
    STATES = {0: "STARTED", 1: "PLACED", 2: "CANCELED", 3: "PARTIAL",
              4: "FILLED", 5: "REJECTED", 6: "EXPIRED"}
    print("%d live order(s):" % len(ords))
    for o in ords:
        print("  ticket=%-12d magic=%-9s %-10s vol=%.2f price=%.*f sl=%s tp=%s %s"
              % (o.ticket, o.magic, TYPES.get(o.type, o.type),
                 o.volume_current, dg, o.price_open,
                 ("%.*f" % (dg, o.sl)) if o.sl else "-",
                 ("%.*f" % (dg, o.tp)) if o.tp else "-",
                 STATES.get(o.state, o.state)))

pos = mt5.positions_get(symbol="XAUUSD")
print("positions: %d" % (len(pos) if pos else 0))
mt5.shutdown()