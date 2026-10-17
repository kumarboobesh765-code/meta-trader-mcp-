r"""One-shot (2026-10-14): cancel every pending order NOT owned by
GridRecoveryEA (magic 930021) on the DEMO account, so retired charts cannot
orphan-fill. Positions are untouched (their server SL/TP still stand).
Refuses anything but a demo account. Sends nothing else.
"""
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import load_env

KEEP_MAGIC = 930021

load_env()
ok = False
for _ in range(4):
    if mt5.initialize():
        ok = True
        break
    print("attach attempt failed: %s" % (mt5.last_error(),))
    mt5.shutdown()
    time.sleep(8)
if not ok:
    print("ATTACH_FAILED")
    sys.exit(3)

try:
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        sys.exit(2)
    ords = mt5.orders_get() or []
    mine = [o for o in ords if o.magic != KEEP_MAGIC]
    if not mine:
        print("no pendings to cancel (kept magic %d)" % KEEP_MAGIC)
        sys.exit(0)
    allok = True
    for o in mine:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE,
                            "order": o.ticket, "magic": o.magic,
                            "comment": "pause cancel"})
        if r is None:
            print("cancel #%d magic=%d ORDER_SEND NONE (%s)"
                  % (o.ticket, o.magic, mt5.last_error()))
            allok = False
        else:
            print("cancel #%d magic=%d ret=%s" % (o.ticket, o.magic, r.retcode))
            allok = allok and r.retcode == mt5.TRADE_RETCODE_DONE
    left = [o for o in (mt5.orders_get() or []) if o.magic != KEEP_MAGIC]
    print("remaining non-grid pendings: %d" % len(left))
    sys.exit(0 if (allok and not left) else 4)
finally:
    mt5.shutdown()
