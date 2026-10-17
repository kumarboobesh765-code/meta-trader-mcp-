"""LIVE trailing-SL audit for every trail-managed twin (read-only, mt5 attach).

For each -T twin position whose champion style is 'trail' (champion_check.streams):
  - ARMED-TRAILING : SL sits on the profit side of entry (evidence of a ratchet)
  - CORRECT-WAIT   : unrealized gain < 1.0 x ATR (strategy tf) -> SL must still
                     be static; nothing to fix
  - SUSPICIOUS     : gain >= 1.0 x ATR but SL never moved past entry -- the
                     trailing engine should have fired; needs a look
Also recomputes the ratchet step (0.3 ATR) and prints the SL trail-distance
residual (bid/ask - 1.2 ATR) for armed positions so we can see the trail is
tuned correctly. Fixed-champion twins are checked only for the OPPOSITE
violation (SL moved past entry where it must stay static).

Run on the VPS: python C:/FTTest/scripts/_diag_trail_audit.py
"""
import sys
import time

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

from forward_test import (SYMBOLS, STRATS, closed_bars, load_env)
from champion_check import streams

TRAIL_FTTEST = (0.10, 0.3, 0.05)  # FTTest twin trail (tightened 2026-10-01, sweep +$1.3k/30d)
TRAIL_AETHER = (0.8, 1.0, 0.25)   # aetherflow-H4 twins: sweep says keep (tightening loses)
TRAIL_AETHER_M30 = (0.2, 0.5, 0.10)  # aetherflow-M30 flip (sweep 2026-10-01: +$343)
TRAIL_SUPERTREND = (0.5, 0.8, 0.20)  # supertrend H1-host verdict (sweep 2026-10-01)


def trail_of(name):
    """Per-family (act, dist, step) the profile deploys -- keep in sync with
    scripts/make_ea_profile.py."""
    if name == "aetherflow-M30":
        return TRAIL_AETHER_M30
    if name.startswith("aetherflow"):
        return TRAIL_AETHER
    if name == "supertrend":
        return TRAIL_SUPERTREND
    return TRAIL_FTTEST


TF_OF = {  # signal timeframe per strategy (mirrors the EAs)
    "breakout": "M15", "meanrev": "M15", "macross": "M30", "straddle": "H1",
    "smc": "M15", "london": "M15", "squeeze": "M15", "profile": "M15",
    "orderflow": "M1", "trendpullback": "M15", "donchian": "H1",
    "trend": "H1", "supres": "H1", "supertrend": "H1",
    "aetherflow": "M15", "aetherflow-M30": "M30", "aetherflow-H4": "H4",
}


def atr_of(symbol, tf):
    import MetaTrader5 as mt5
    tfmap = {"M1": mt5.TIMEFRAME_M1, "M15": mt5.TIMEFRAME_M15,
             "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
             "H4": mt5.TIMEFRAME_H4}
    rates = mt5.copy_rates_from_pos(symbol, tfmap.get(tf, mt5.TIMEFRAME_M15), 1, 30)
    if rates is None or len(rates) < 16:
        return None
    bars = [{"high": r["high"], "low": r["low"], "close": r["close"]}
            for r in rates]
    trs = []
    for i in range(1, len(bars)):
        pc = bars[i - 1]["close"]
        trs.append(max(bars[i]["high"] - bars[i]["low"],
                       abs(bars[i]["high"] - pc), abs(bars[i]["low"] - pc)))
    return sum(trs[-14:]) / 14


def main():
    import json as _json
    json_out = None
    if "--json" in sys.argv:
        json_out = sys.argv[sys.argv.index("--json") + 1]
    env = load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    print("trailing audit on %s (demo ok)" % acc.server)
    slots = streams()
    armed = wait = suspicious = fixed_bad = 0
    lines = []
    for sym, name, base_m, twin_m, champ in slots:
        poss = [p for p in (mt5.positions_get(symbol=sym) or [])
                if p.magic == twin_m]
        if not poss:
            continue
        tf = TF_OF.get(name, "M15")
        a = atr_of(sym, tf)
        act, dist, _step = trail_of(name)
        tick = mt5.symbol_info_tick(sym)
        for p in poss:
            label = "%s %s-T" % (sym, name)
            entry, sl = p.price_open, p.sl
            if champ == "trail":
                cur = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                gain = (cur - entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (entry - cur)
                moved = (sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < sl < entry)
                if moved:
                    armed += 1
                    resid = (cur - dist * a - sl) if a else 0
                    point = mt5.symbol_info(sym).point
                    lines.append("  %-22s ARMED  sl=%.5f entry=%.5f gain=%.2f ATR "
                                 "(trail residual %.1f pts) OK"
                                 % (label, sl, entry, gain / a if a else 0,
                                    resid / point if point else 0))
                elif a and gain >= act * a:
                    suspicious += 1
                    lines.append("  %-22s SUSPICIOUS gain=%.2f ATR >= activation "
                                 "%.1f but sl=%.5f still static (entry=%.5f)"
                                 % (label, gain / a, act, sl, entry))
                else:
                    wait += 1
                    lines.append("  %-22s WAIT   gain=%.2f ATR (< activation) sl "
                                 "static correctly" % (label, gain / a if a else 0))
            else:
                bad = (sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < sl < entry)
                if bad:
                    fixed_bad += 1
                    lines.append("  %-22s VIOLATION fixed champion but SL moved "
                                 "past entry (sl=%.5f)" % (label, sl))
    print("trail-champion twins: %d armed, %d waiting (correct), %d suspicious"
          % (armed, wait, suspicious))
    print("fixed-champion twins with moved SL: %d" % fixed_bad)
    aet_lines = []

    # aetherflow -T twins (9600xx) + SMVP are outside champion_check.streams()
    def _emit(s):
        print(s)
        aet_lines.append(s.strip())

    print("-- aetherflow -T twins + SMVP --")
    AET = {960001: ("aetherflow", "M15", "trail"),
           960002: ("aetherflow-M30", "M30", "trail"),
           960003: ("aetherflow-H4", "H4", "trail"),
           26092501: ("smvp", "M1", "own")}
    for p in (mt5.positions_get() or []):
        if p.magic not in AET:
            continue
        name, tf, kind = AET[p.magic]
        a = atr_of(p.symbol, tf)
        entry, sl = p.price_open, p.sl
        tick = mt5.symbol_info_tick(p.symbol)
        cur = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        gain = (cur - entry) if p.type == mt5.POSITION_TYPE_BUY else (entry - cur)
        moved = (sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
            else (0 < sl < entry)
        if kind == "own":
            _emit("  %-22s %-6s open sl=%.2f entry=%.2f gain=%.2f ATR "
                  "(R-based chandelier, own logic)"
                  % (name + " (" + str(p.magic) + ")", "OPEN", sl, entry,
                     gain / a if a else 0))
            continue
        act, dist = trail_of(name)[0], trail_of(name)[1]
        if moved:
            resid = (cur - dist * a - sl) if a else 0
            _emit("  %-22s ARMED   gain=%.2f ATR sl=%.2f resid=%+.0f pts %s"
                  % (name + "-T", gain / a if a else 0, sl,
                     resid / mt5.symbol_info(p.symbol).point,
                     "OK" if abs(resid) < a else "OFF!"))
        elif a and gain >= act * a:
            suspicious += 1
            _emit("  %-22s SUSPICIOUS gain=%.2f ATR >= %.1f but sl static"
                  % (name + "-T", gain / a, act))
        else:
            _emit("  %-22s WAIT    gain=%.2f ATR (< %.1f activation)"
                  % (name + "-T", gain / a if a else 0, act))
    for l in lines:
        print(l)
    if suspicious == 0 and fixed_bad == 0:
        print("VERDICT: trailing engine working perfectly on every open twin")
    if json_out:
        try:
            _json.dump({"ts": time.time(), "armed": armed, "waiting": wait,
                        "suspicious": suspicious, "fixed_bad": fixed_bad,
                        "lines": lines + aet_lines}, open(json_out, "w"))
        except OSError as e:
            print("json write failed: %r" % e)
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
