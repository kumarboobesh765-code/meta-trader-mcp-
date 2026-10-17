"""Decisive server-clock probe: measures pending-order freshness entirely in
SERVER epochs (no local-TZ conversions), so we can tell whether the straddle
EAs re-armed at the latest H1 boundaries or went quiet."""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\FTTest\scripts")


def fmt(epoch):
    return datetime.utcfromtimestamp(epoch).strftime("%m-%d %H:%M:%S") if epoch else "0"


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("init failed", mt5.last_error())
        return 1
    try:
        tick = mt5.symbol_info_tick("XAUUSD")
        now_srv = int(tick.time)                # server epoch, per broker
        print("server now           : %s  (epoch %d)" % (fmt(now_srv), now_srv))

        print()
        print("=== straddle pendings, server-clock ages ===")
        for o in (mt5.orders_get(symbol="XAUUSD") or []):
            if o.magic not in (930004, 940004):
                continue
            age_min = (now_srv - o.time_setup) / 60.0
            kind = "BUY_STP" if o.type == 4 else ("SELL_STP" if o.type == 5 else str(o.type))
            print("magic %d  #%d %s @ %.2f  set %s  age %6.1f min"
                  % (o.magic, o.ticket, kind, o.price_open, fmt(o.time_setup), age_min))

        print()
        print("=== straddle last activity (deals/server clock) ===")
        deals = mt5.history_deals_get(now_srv - 8 * 3600, now_srv + 60) or []
        last_in = {}
        for d in deals:
            if d.symbol != "XAUUSD" or d.magic not in (930004, 940004):
                continue
            tag = "IN " if d.entry == mt5.DEAL_ENTRY_IN else ("OUT" if d.entry == mt5.DEAL_ENTRY_OUT else "...")
            last_in.setdefault(d.magic, []).append((d.time, tag, d.price, d.profit))
        for m in sorted(last_in):
            evs = sorted(last_in[m])[-4:]
            for t, tag, px, pr in evs:
                print("magic %d  %s %s @ %.2f  pnl %+.2f  at %s  age %6.1f min"
                      % (m, tag, "buy" if m and px == px else "", px, pr,
                         fmt(t), (now_srv - t) / 60.0))

        print()
        print("=== journal-vs-server freshness: last H1 bar close ===")
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 1, 3)
        if rates is not None and len(rates):
            last = rates[-1]
            print("last closed H1 bar open: %s  (epoch %d)  -> EA 'hour key' = %s"
                  % (fmt(int(last["time"])), int(last["time"]),
                     fmt(int(last["time"]) - int(last["time"]) % 3600)))
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
