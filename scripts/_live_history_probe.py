r"""Read-only full history probe for the NEW account (33705313, REAL cent).
Dumps deals + orders from broker history and positions, grouped by magic and
symbol, with price/time patterns and comments, so the strategy behind the
account can be identified. Sends NOTHING.
"""
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, "C:/FTTest/scripts")
import MetaTrader5 as mt5
from forward_test import load_env

load_env()
ok = False
for _ in range(4):
    if mt5.initialize():
        ok = True
        break
    time.sleep = __import__("time").sleep
    print("attach attempt failed: %s" % (mt5.last_error(),))
    mt5.shutdown()
    __import__("time").sleep(8)
if not ok:
    print("ATTACH_FAILED")
    sys.exit(3)


def ts(x):
    return datetime.utcfromtimestamp(int(x)).strftime("%m-%d %H:%M:%S")


try:
    acc = mt5.account_info()
    MODE = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(
        acc.trade_mode if acc else 2, "?")
    print("account %s mode=%s server=%s bal=%.2f eq=%.2f currency=%s" % (
        acc.login if acc else "?", MODE, acc.server if acc else "?",
        acc.balance, acc.equity, acc.currency))
    now = datetime.now(timezone.utc)

    deals = mt5.history_deals_get(now - timedelta(days=60),
                                  now + timedelta(days=2)) or []
    print("\n=== DEALS (%d in last 60d) ===" % len(deals))
    by_magic = defaultdict(lambda: {"n": 0, "in": 0, "out": 0, "vol": 0.0,
                                    "net": 0.0, "syms": set(), "comments": [],
                                    "first": None, "last": None})
    for d in deals:
        if d.type == mt5.DEAL_TYPE_BALANCE:
            # balance ops: 0=demo deposit, 1=real deposit, 2=withdrawal,
            # 3=initial balance, 4..: credits/surcharge etc.
            key = "BALOP%d" % d.entry
        else:
            key = d.magic
        b = by_magic[key]
        b["n"] += 1
        if d.entry == mt5.DEAL_ENTRY_IN:
            b["in"] += 1
        else:
            b["out"] += 1
        b["vol"] += d.volume
        b["net"] += d.profit + d.commission + d.swap
        if d.symbol:
            b["syms"].add(d.symbol)
        if d.comment:
            b["comments"].append("%s|%s" % (d.comment, d.profit))
        if b["first"] is None or d.time < b["first"]:
            b["first"] = d.time
        b["last"] = d.time
    for k, b in sorted(by_magic.items(), key=lambda kv: kv[1]["last"] or 0):
        print("magic %s | deals=%d in=%d out=%d vol=%.2f net=%+.2f | syms=%s "
              "| first=%s last=%s"
              % (k, b["n"], b["in"], b["out"], b["vol"], b["net"],
                 sorted(b["syms"]), ts(b["first"]), ts(b["last"])))
        # distinct comment shapes
        shapes = sorted(set(c.split("|")[0] for c in b["comments"])
                        if b["comments"] else [])
        print("   comment shapes: %s  | sample: %s"
              % (shapes[:8], b["comments"][-3:]))

    print("\n=== FULL DEAL FLOW (chronological, entry/exit pairs) ===")
    for d in sorted(deals, key=lambda x: x.time):
        side = {mt5.DEAL_TYPE_BUY: "buy", mt5.DEAL_TYPE_SELL: "sell"}
        entry = {0: "in", 1: "out", 2: "inout", 3: "out-by"}
        print("%s #%d %s %s %.2f @ %.3f magic=%d entry=%s pnl=%+.2f cmt=%s"
              % (ts(d.time), d.ticket, d.symbol, side.get(d.type, d.type),
                 d.volume, d.price, d.magic,
                 entry.get(d.entry, d.entry), d.profit,
                 (d.comment or "")[:40]))

    ords = mt5.history_orders_get(now - timedelta(days=60),
                                  now + timedelta(days=2)) or []
    print("\n=== ORDERS (%d in last 60d) ===" % len(ords))
    otypes = {2: "BUY_LIM", 3: "SELL_LIM", 4: "BUY_STP", 5: "SELL_STP", 0: "BUY",
              1: "SELL"}
    from collections import Counter
    c = Counter("%s %s" % (o.magic, otypes.get(o.type, o.type)) for o in ords)
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print("   %s -> %d orders" % (k, v))
    for o in sorted(ords, key=lambda x: x.time_setup)[-25:]:
        print("%s #%d %s %s %.2f @ %.3f sl=%.3f tp=%.3f magic=%d state=%s cmt=%s"
              % (ts(o.time_setup), o.ticket, o.symbol,
                 otypes.get(o.type, o.type), o.volume_current, o.price_open,
                 o.sl, o.tp, o.magic, o.state, (o.comment or "")[:30]))

    poss = mt5.positions_get() or []
    print("\n=== OPEN POSITIONS (%d) ===" % len(poss))
    for p in poss:
        print("#%d magic=%d %s %s %.2f @ %.3f sl=%.3f tp=%.3f pnl=%+.2f "
              "open=%s cmt=%s"
              % (p.ticket, p.magic, p.symbol,
                 "buy" if p.type == 0 else "sell", p.volume, p.price_open,
                 p.sl, p.tp, p.profit, ts(p.time), (p.comment or "")[:40]))
finally:
    mt5.shutdown()
