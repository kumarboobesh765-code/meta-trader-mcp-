r"""One-shot live account probe (read-only, demo rail): open positions,
pending orders and last-24h closed trades grouped by magic, named per the
runner's MAGICS map. Prints a compact table; nothing is traded."""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\FTTest\scripts")
try:
    from forward_test import MAGICS  # the rig's canonical magic->name map
except Exception:
    MAGICS = {}


def name(magic):
    return MAGICS.get(magic, "UNMAPPED(%d)" % magic)


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("mt5.initialize() failed:", mt5.last_error())
        return 1
    try:
        acc = mt5.account_info()
        if acc is None:
            print("account_info() None")
            return 1
        if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            print("REFUSED: not a demo account (trade_mode=%s)" % acc.trade_mode)
            return 1
        print("account %s @ %s  balance %.2f  equity %.2f"
              % (acc.login, acc.server, acc.balance, acc.equity))
        print()

        poss = mt5.positions_get() or []
        print("=== OPEN POSITIONS (%d) ===" % len(poss))
        by_magic = {}
        for p in sorted(poss, key=lambda x: x.magic):
            by_magic.setdefault(p.magic, []).append(p)
        for m, ps in sorted(by_magic.items()):
            net = sum(p.profit for p in ps)
            print("%-9d %-22s %d pos  net %+.2f" % (m, name(m), len(ps), net))
            for p in ps:
                side = "buy" if p.type == 0 else "sell"
                since = datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%m-%d %H:%M")
                fmt = getattr(p, "price_open", None)
                px = getattr(p, "price_current", None)
                print("    #%d %s %.2f @ %.2f now %.2f  sl %.2f tp %.2f  open %s UTC"
                      % (p.ticket, side, p.volume, fmt or 0, px or 0,
                         p.sl, p.tp, since))
        if not poss:
            print("  (none)")

        ords = mt5.orders_get() or []
        print()
        print("=== PENDING ORDERS (%d) ===" % len(ords))
        by_magic = {}
        for o in ords:
            by_magic.setdefault(o.magic, []).append(o)
        for m, os_ in sorted(by_magic.items()):
            print("%-9d %-22s %d pend" % (m, name(m), len(os_)))
            for o in os_:
                kinds = {2: "BUY_LIM", 3: "SELL_LIM", 4: "BUY_STP", 5: "SELL_STP"}
                since = datetime.fromtimestamp(o.time_setup, tz=timezone.utc).strftime("%m-%d %H:%M")
                print("    #%d %s %.2f @ %.2f  sl %.2f tp %.2f  set %s UTC"
                      % (o.ticket, kinds.get(o.type, str(o.type)), o.volume_current,
                         o.price_open, o.sl, o.tp, since))
        if not ords:
            print("  (none)")

        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(hours=24), now + timedelta(minutes=5)) or []
        print()
        print("=== CLOSED TRADE FLOWS, LAST 24H ===")
        flows = {}
        for d in deals:
            if d.entry != mt5.DEAL_ENTRY_OUT and d.entry != mt5.DEAL_ENTRY_INOUT:
                continue
            f = flows.setdefault(d.magic, {"n": 0, "net": 0.0})
            f["n"] += 1
            f["net"] += d.profit + d.commission + d.swap
        if not flows:
            print("  (no exits in the last 24h)")
        for m, f in sorted(flows.items()):
            print("%-9d %-22s %3d closes  net %+.2f" % (m, name(m), f["n"], f["net"]))
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
