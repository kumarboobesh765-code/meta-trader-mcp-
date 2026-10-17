"""Read-only: list open positions and pending orders with their comments. No trading."""
import subprocess
import MetaTrader5 as mt5

out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout.lower()
if "terminal64.exe" not in out and "terminal.exe" not in out:
    print("MT5 not running")
    raise SystemExit(1)

mt5.initialize()
print("POSITIONS:")
for p in (mt5.positions_get() or []):
    print("  #%d magic=%d %s %.2f @ %.2f sl=%.2f tp=%.2f comment=%r"
          % (p.ticket, p.magic, "BUY " if p.type == 0 else "SELL", p.volume,
             p.price_open, p.sl, p.tp, p.comment))
print("PENDING ORDERS:")
for o in (mt5.orders_get() or []):
    print("  #%d magic=%d type=%d %.2f @ %.2f sl=%.2f tp=%.2f comment=%r"
          % (o.ticket, o.magic, o.type, o.volume_current, o.price_open,
             o.sl, o.tp, o.comment))
if not (mt5.positions_get() or []) and not (mt5.orders_get() or []):
    print("  (none)")
mt5.shutdown()
