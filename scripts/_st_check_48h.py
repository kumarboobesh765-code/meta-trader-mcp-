r"""Supertrend 48h live-vs-backtest check (one-shot, scheduled ~48h after
the twins went live 2026-09-30 15:44 UTC).

Compares the twins' first 48h of live behavior against the corrected
backtest expectation:
  - how many ST(5,2.0) flips actually occurred on live H1 data in the window
    (recomputed from bars with the faithful port), vs how many trips the EAs
    took (misses are legitimate: flips while already in a position are
    hold-through/reverse, entry is next bar open, spread gate)
  - per closed trip: adverse move vs the assumed 2 x ATR(14) stop
    (ATR at entry time from live H1 data) -> catches SL slippage
  - verdict + Telegram. File-based where possible; needs one short MT5
    attach for bars/history (retry ladder; degrades to trade-count-only).

Run: python C:/FTTest/scripts/_st_check_48h.py
"""
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "C:/FTTest/scripts")

FT = r"C:\FTTest"
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
MAGICS = (930014, 940014)
LABEL = {930014: "supertrend", 940014: "supertrend-T"}


def telegram(text):
    import subprocess
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def main():
    from forward_test import load_env, closed_bars
    import MetaTrader5 as mt5
    load_env()
    ok = False
    for attempt in range(5):
        if mt5.initialize():
            ok = True
            break
        print("attach %d failed: %s" % (attempt + 1, mt5.last_error()))
        mt5.shutdown()
        time.sleep(10)
    if not ok:
        msg = "ST-48h check: mt5 attach failed after retries -- rerun me"
        print(msg)
        telegram(msg)
        return 3
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        return 2

    go_live = datetime(2026, 9, 30, 15, 44, tzinfo=timezone.utc).timestamp()
    t0 = go_live
    now = time.time()

    # expected signal count: faithful ST on the LIVE H1 series
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bts", r"C:\FTTest\scripts\backtest_supertrend.py")
    bts = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(bts)
        h1 = closed_bars("XAUUSD", "H1", 900)
        dirs = bts.st_dir_pine(h1, 5, 2.0)
        flips = sum(1 for i in range(1, len(h1))
                    if h1[i]["time"] >= t0 and dirs[i] != dirs[i - 1]) \
            if len(h1) > 60 else -1
    except SystemExit:
        flips = -1  # import deps missing -> skip expectation, count trades only

    deals = mt5.history_deals_get(t0 - 3600, now + 4 * 3600) or []
    trips = {}
    for d in deals:
        if d.magic not in MAGICS:
            continue
        if d.entry == 0:
            trips.setdefault(d.position_id, {})["in"] = d
        elif d.entry == 1:
            trips.setdefault(d.position_id, {})["out"] = d
    mt5.shutdown()

    done = [v for v in trips.values() if "in" in v and "out" in v]
    lines = ["ST-48h: %s (live since %s)"
             % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                datetime.fromtimestamp(go_live, timezone.utc)
                .strftime("%m-%d %H:%M"))]
    if flips >= 0:
        lines.append("ST(5,2.0) flips on live H1 since go-live: %d | "
                     "EA trips opened: %d (closed: %d)"
                     % (flips, len(trips), len(done)))
    per = {m: sum(1 for v in trips.values() if v["in"].magic == m) for m in MAGICS}
    lines.append("per twin: " + " | ".join("%s=%d" % (LABEL[m], per[m])
                                           for m in MAGICS))
    worst = 0.0
    net = 0.0
    for v in done:
        i, o = v["in"], v["out"]
        pnl = o.profit + o.commission + o.swap
        net += pnl
        move = abs(o.price - i.price)
        try:
            import MetaTrader5 as mt5b
            mt5b.initialize()  # brief reattach for ATR context (best effort)
            rates = mt5b.copy_rates_from("XAUUSD", mt5b.TIMEFRAME_H1, 1, 400)
            mt5b.shutdown()
            trs = []
            for k in range(1, len(rates)):
                pc = rates[k - 1]["close"]
                trs.append((max(rates[k]["high"] - rates[k]["low"],
                                abs(rates[k]["high"] - pc),
                                abs(rates[k]["low"] - pc)), rates[k]["time"]))
            win = [tr for tr, t in trs if t <= i.time]
            a = sum(win[-14:]) / 14.0 if len(win) >= 14 else None
        except Exception:
            a = None
        atr_s = ("%.2f ATR" % (move / a)) if a and a > 0 else "ATR n/a"
        if a and a > 0:
            worst = max(worst, move / a)
        lines.append("  #%d %s %s pnl=%+.2f move=$%.2f (%s)"
                     % (i.position_id, LABEL[i.magic],
                        "WIN" if pnl > 0 else "LOSS", pnl, move, atr_s))
    lines.append("closed-trip net: %+.2f | worst adverse move: %.2f ATR "
                 "(assumed SL 2.0 ATR)" % (net, worst))
    if flips >= 0:
        if len(trips) == 0 and flips > 0:
            lines.append("VERDICT: PROBLEM -- %d flips but zero EA trips; "
                         "investigate the supertrend charts" % flips)
        elif worst > 2.5:
            lines.append("VERDICT: SL SLIPPAGE -- worst trip %.2f ATR beyond "
                         "the 2.0 ATR assumption" % worst)
        else:
            lines.append("VERDICT: ON TRACK (0-%d trips/48h is within the "
                         "~21/30d backtest cadence given flip timing)" % flips)
    msg = "\n".join(lines)
    print(msg)
    telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
