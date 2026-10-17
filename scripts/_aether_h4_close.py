"""Close the stale aetherflow-H4 twins (950003 fixed / 960003 trail).

Decision 2026-10-02: the 27h short opened 10-01 04:00 at 4145 is a stale UT
signal with -$42/twin floating; price must rise $15.76 to hit SL (-$58 cap)
vs fall $129 to reach TP -- ~8:1 against inside the 20h before the new
12-bar cap fires. Demo account only. Verifies the journal afterwards.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import load_env

MAGICS = (950003, 960003)


def main():
    dry = "--dry" in sys.argv
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: non-demo account")
        mt5.shutdown()
        return 1
    print("account %s demo ok | bal=%.2f" % (acc.login, acc.balance))
    poss = [p for p in (mt5.positions_get() or []) if p.magic in MAGICS]
    if not poss:
        print("nothing to close (no %s positions)" % (MAGICS,))
        mt5.shutdown()
        return 0
    total = 0.0
    for p in poss:
        fl = p.profit + p.swap
        total += fl
        age_h = (time.time() - p.time) / 3600.0
        print("\nmagic %d ticket %d %s @ %.2f  fl=%+.2f age=%.1fh"
              % (p.magic, p.ticket,
                 "SELL" if p.type == mt5.POSITION_TYPE_SELL else "BUY",
                 p.price_open, fl, age_h))
        if dry:
            print("  DRY RUN -- not closing")
            continue
        # Vantage XAUUSD accepts ONLY IOC on close. Probed with order_check
        # (scripts/_fillmode_scan.py): omitted/FOK/RETURN -> 10030, IOC -> 0.
        # The enum values in this MT5 build are FOK=0 IOC=1 RETURN=2, so the
        # symbol filling_mode bitmask reads as 2 while IOC is what works.
        si = mt5.symbol_info(p.symbol)
        filling = mt5.ORDER_FILLING_IOC
        if si is not None:
            probe = mt5.order_check({
                "symbol": p.symbol, "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket, "volume": p.volume,
                "type": mt5.ORDER_TYPE_BUY
                if p.type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL,
                "deviation": 50, "magic": p.magic,
                "type_filling": filling})
            if probe.retcode != 0:
                print("  IOC rejected by order_check (%s) -- aborting, not "
                      "blind-sending" % probe.retcode)
                continue
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
               "position": p.ticket, "volume": p.volume,
               "type": mt5.ORDER_TYPE_BUY if p.type == mt5.POSITION_TYPE_SELL
               else mt5.ORDER_TYPE_SELL,
               "deviation": 50, "magic": p.magic, "comment": "aetherH4-stale",
               "type_filling": filling}
        res = mt5.order_send(req)
        # 0 = TRADE_RETCODE_DONE, 10009 = TRADE_RETCODE_DONE_PARTIAL/FILLED
        # ("Request executed") -- both mean the close went through.
        if res and res.retcode in (0, 10009):
            print("  CLOSED retcode=%s (%s) price=%s"
                  % (res.retcode, res.comment, res.price))
        else:
            print("  CLOSE FAILED retcode=%s (%s)"
                  % (res.retcode if res else None,
                     res.comment if res else "no response"))
        time.sleep(1)
    print("\nrealized this pass: %+.2f (floating at close time)" % total)
    if not dry:
        time.sleep(2)
        left = [p for p in (mt5.positions_get() or []) if p.magic in MAGICS]
        print("remaining aetherflow-H4 positions: %d" % len(left))
        for p in left:
            print("  magic %d still open @ %.2f fl=%+.2f"
                  % (p.magic, p.price_open, p.profit + p.swap))
        acc2 = mt5.account_info()
        print("bal=%.2f eq=%.2f" % (acc2.balance, acc2.equity))
        # confirm the fills landed in history (OUT deals on our magics)
        frm = datetime.now(timezone.utc) - timedelta(hours=1)
        hist = [d for d in (mt5.history_deals_get(frm, datetime.now(timezone.utc))
                            or []) if d.magic in MAGICS and d.entry == 1]
        for d in hist:
            print("  fill: %s %s %.2f @ %.2f pnl=%+.2f"
                  % (datetime.fromtimestamp(d.time, tz=timezone.utc)
                     .strftime("%H:%M:%S"), "BUY" if d.type == 0 else "SELL",
                     d.volume, d.price, d.profit + d.commission + d.swap))
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
