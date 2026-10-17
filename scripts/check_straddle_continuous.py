r"""Continuous straddle health checker + live-account slippage/spread model.

Reads the live DEMO account through the MetaTrader5 python API (read-only:
no orders sent, nothing modified, MT5 is never launched or killed).

Usage:
  python scripts/check_straddle_continuous.py --once            # single pass
  python scripts/check_straddle_continuous.py --cpu             # 10s loop
  python scripts/check_straddle_continuous.py --cpu --interval 30
  python scripts/check_straddle_continuous.py --stop            # stop a --cpu run
  python scripts/check_straddle_continuous.py --flag            # show+clear stop flag

What one pass produces (stdout + logs/_straddle_continuous_checkpoint.json):

  1. SPREAD MODEL   ask/bid/spread now, plus the spread distribution over
                    the trailing hour of ticks (min/median/p90/max) and the
                    spread expressed in points and as % of ATR(H1,14).
  2. SLIPPAGE MODEL realized slippage per straddle fill from deal history:
                    deal.price vs the stop order's trigger level (price_open),
                    per side, in $, points and % of ATR -- plus the worst-case
                    model bound (spread at trigger) for unfilled levels.
  3. EA STATE       live pending orders / open positions for magics
                    930004 (fixed) and 940004 (trailing).
  4. HEALTH         demo-account rail, terminal link, order hygiene.

The straddle viability question this answers: entry buffer is 0.25 ATR
beyond the range edge. If the live spread eats a large share of that buffer,
every fill starts under water -- the model quantifies exactly that cost.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs")
CHECKPOINT = os.path.join(LOG, "_straddle_continuous_checkpoint.json")
FLAG_FILE = os.path.join(LOG, "_straddle_continuous_stop.flag")

STRADDLE_MAGICS = (930004, 940004)   # fixed / trailing twins
BUFFER_ATR = 0.25                    # entry buffer beyond range edge (x ATR)


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def load_env():
    env = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def mt5_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True,
                         errors="replace").stdout.lower()
    return "terminal64.exe" in out


def read_flag():
    if os.path.exists(FLAG_FILE):
        with open(FLAG_FILE) as f:
            return f.read().strip()
    return ""


def remove_flag():
    try:
        os.remove(FLAG_FILE)
    except OSError:
        pass


def set_flag(msg="stop requested"):
    os.makedirs(LOG, exist_ok=True)
    with open(FLAG_FILE, "w") as f:
        f.write(msg)


def write_checkpoint(ck):
    os.makedirs(LOG, exist_ok=True)
    with open(CHECKPOINT, "w") as f:
        json.dump(ck, f, indent=2)


# ------------------------------------------------------------------ model bits

def atr_from_rates(rates, period=14):
    if rates is None or len(rates) < period + 1:
        return None
    trs = []
    for i in range(1, len(rates)):
        h, l, pc = rates[i]["high"], rates[i]["low"], rates[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return float(sum(trs[-period:]) / period)


def spread_model(mt5, symbol, point, atr, now):
    """Spread now + distribution over the trailing hour of ticks, normalized."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.bid <= 0 or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    model = {
        "bid": round(tick.bid, 2),
        "ask": round(tick.ask, 2),
        "spread": round(spread, 2),
        "spread_points": round(spread / point) if point else None,
        "mid": round((tick.ask + tick.bid) / 2.0, 2),
    }
    if atr:
        model["spread_atr_pct"] = round(spread / atr * 100, 2)   # spread as % of ATR
        model["buffer_atr"] = BUFFER_ATR
        model["buffer_abs"] = round(BUFFER_ATR * atr, 2)
        model["spread_vs_buffer_pct"] = round(spread / (BUFFER_ATR * atr) * 100, 1)
    # trailing-hour tick distribution (INFO ticks carry bid/ask)
    try:
        t_from = now - timedelta(hours=1)
        ticks = mt5.copy_ticks_range(symbol, t_from, now, mt5.COPY_TICKS_INFO)
        if ticks is not None and len(ticks) > 0:
            sp = [float(t["ask"] - t["bid"]) for t in ticks
                  if t["ask"] > 0 and t["bid"] > 0]
            if sp:
                sp.sort()
                model["hour_ticks"] = len(sp)
                model["hour_min"] = round(sp[0], 2)
                model["hour_median"] = round(statistics.median(sp), 2)
                model["hour_p90"] = round(sp[int(len(sp) * 0.9)], 2)
                model["hour_max"] = round(sp[-1], 2)
                model["hour_median_points"] = round(
                    statistics.median(sp) / point) if point else None
    except Exception as e:
        model["hour_error"] = str(e)
    return model


def realized_slippage(mt5, symbol, point, atr, now, days=14):
    """Realized slippage per straddle fill from deal history.

    For each DEAL_ENTRY_IN of magics 930004/940004: slippage = deal.price
    minus the stop order's trigger level (order.price_open). BUY fills at
    or above the trigger; SELL fills at or below it. Positive = worse than
    requested, negative = price improvement.
    """
    res = {"days": days, "fills": 0, "by_side": {}, "examples": []}
    try:
        deals = mt5.history_deals_get(now - timedelta(days=days), now + timedelta(minutes=5))
    except Exception as e:
        res["error"] = str(e)
        return res
    if not deals:
        return res
    sides = {}
    for d in deals:
        if d.symbol != symbol or d.magic not in STRADDLE_MAGICS:
            continue
        if d.entry != mt5.DEAL_ENTRY_IN:
            continue
        trigger = None
        try:
            ords = mt5.history_orders_get(position=d.position_id)
            for o in (ords or []):
                if o.ticket == d.order:
                    trigger = o.price_open
                    break
        except Exception:
            pass
        is_buy = d.type == mt5.DEAL_TYPE_BUY
        if trigger:
            slip = float((d.price - trigger) if is_buy else (trigger - d.price))
        else:
            slip = None
        side = "buy" if is_buy else "sell"
        s = sides.setdefault(side, {"n": 0, "slips": [], "worst": None})
        s["n"] += 1
        if slip is not None:
            s["slips"].append(slip)
            if s["worst"] is None or slip > s["worst"]:
                s["worst"] = slip
        if len(res["examples"]) < 5:
            res["examples"].append({
                "time_utc": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                "magic": d.magic, "side": side, "lots": float(d.volume),
                "trigger": float(trigger) if trigger else None,
                "fill": round(float(d.price), 2),
                "slippage": round(slip, 2) if slip is not None else None,
                "slippage_points": round(slip / point) if (slip is not None and point) else None,
                "slippage_atr_pct": round(slip / atr * 100, 2)
                                    if (slip is not None and atr) else None,
            })
    res["fills"] = sum(s["n"] for s in sides.values())
    for side, s in sides.items():
        out = {"n": s["n"]}
        if s["slips"]:
            slips = [float(x) for x in s["slips"]]
            out["avg_slippage"] = round(sum(slips) / len(slips), 2)
            out["max_slippage"] = round(max(slips), 2)
            out["min_slippage"] = round(min(slips), 2)
            if atr:
                out["avg_slippage_atr_pct"] = round(
                    (sum(slips) / len(slips)) / atr * 100, 2)
        res["by_side"][side] = out
    return res


# ------------------------------------------------------------------ one pass

def check_once(symbol="XAUUSD", atr_period=14, log_file=None):
    import MetaTrader5 as mt5

    ck = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "terminal_running": mt5_running(),
        "spread_model": None,
        "atr": None,
        "slippage_realized": None,
        "orders": [],
        "positions": [],
        "watch": [],
        "healthy": False,
        "stop": read_flag(),
    }
    try:
        if not mt5.initialize():
            ck["watch"].append("mt5.initialize() failed: %s" % (mt5.last_error(),))
            return ck
        acc = mt5.account_info()
        if acc is None:
            ck["watch"].append("account_info() returned None")
            return ck
        if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            ck["watch"].append("REFUSED: not a demo account (trade_mode=%s)"
                               % acc.trade_mode)
            return ck
        ck["account"] = {"login": acc.login, "server": acc.server,
                         "balance": acc.balance, "equity": acc.equity}

        info = mt5.symbol_info(symbol)
        if info is None:
            ck["watch"].append("symbol %s not found" % symbol)
            return ck
        mt5.symbol_select(symbol, True)
        point = info.point or 0.01
        now = datetime.now(timezone.utc)

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, 200)
        atr = atr_from_rates(rates, atr_period)
        ck["atr"] = round(atr, 2) if atr else None

        ck["spread_model"] = spread_model(mt5, symbol, point, atr, now)

        # ---- EA state: straddle pendings + positions ----
        ords = mt5.orders_get(symbol=symbol) or []
        ck["orders"] = [{"ticket": o.ticket,
                         "type": int(o.type),      # 4=BUY_STOP 5=SELL_STOP
                         "price": o.price, "sl": o.sl, "tp": o.tp,
                         "magic": o.magic, "lots": o.volume_current}
                        for o in ords if o.magic in STRADDLE_MAGICS]
        poss = mt5.positions_get(symbol=symbol) or []
        ck["positions"] = [{"ticket": p.ticket, "type": int(p.type),
                            "open": p.price_open, "sl": p.sl, "tp": p.tp,
                            "magic": p.magic, "lots": p.volume,
                            "profit": round(p.profit, 2)}
                           for p in poss if p.magic in STRADDLE_MAGICS]

        ck["slippage_realized"] = realized_slippage(mt5, symbol, point, atr, now)

        # ---- health signals ----
        if not ck["terminal_running"]:
            ck["watch"].append("terminal64.exe NOT in tasklist (stale link?)")
        if atr and ck["spread_model"]:
            svb = ck["spread_model"].get("spread_vs_buffer_pct")
            if svb is not None and svb > 50:
                ck["watch"].append("spread consumes %.0f%% of the %.2f-ATR entry "
                                   "buffer -- fills start deeply under water"
                                   % (svb, BUFFER_ATR))
        if not ck["orders"] and not ck["positions"]:
            ck["watch"].append("no straddle orders/positions on %s "
                               "(EA not attached or outside arming window?)" % symbol)
        ck["healthy"] = not any(w.startswith(("REFUSED", "mt5.initialize"))
                                for w in ck["watch"])
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
    write_checkpoint(ck)
    if log_file:
        with open(log_file, "a") as f:
            f.write(json.dumps(ck, indent=2) + "\n")
    return ck


def print_report(ck):
    sm = ck.get("spread_model") or {}
    log("tick  bid %s  ask %s  spread %s (%s pts)" % (
        sm.get("bid"), sm.get("ask"), sm.get("spread"), sm.get("spread_points")))
    log("spread hour: median %s  p90 %s  max %s  over %s ticks" % (
        sm.get("hour_median"), sm.get("hour_p90"), sm.get("hour_max"),
        sm.get("hour_ticks", 0)))
    log("ATR(H1,14) %s | spread = %s%% of ATR | spread = %s%% of the %.2f-ATR buffer"
        % (ck.get("atr"), sm.get("spread_atr_pct"),
           sm.get("spread_vs_buffer_pct"), BUFFER_ATR))
    sl = ck.get("slippage_realized") or {}
    log("realized slippage (%dd): %d fills | buy %s | sell %s"
        % (sl.get("days", 0), sl.get("fills", 0),
           sl.get("by_side", {}).get("buy"),
           sl.get("by_side", {}).get("sell")))
    for ex in (sl.get("examples") or [])[:3]:
        log("  fill ex: %s %s %.2f lots trigger %s fill %s slip %s (%s pts)"
            % (ex["time_utc"][:16], ex["side"], ex["lots"], ex["trigger"],
               ex["fill"], ex["slippage"], ex["slippage_points"]))
    log("EA state: %d pendings, %d positions | healthy=%s"
        % (len(ck["orders"]), len(ck["positions"]), ck["healthy"]))
    for w in ck["watch"]:
        log("  watch: %s" % w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    ap.add_argument("--cpu", action="store_true",
                    help="tick at --interval until the stop flag or Ctrl+C")
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--stop", action="store_true",
                    help="stop any running continuous checker")
    ap.add_argument("--flag", action="store_true",
                    help="show and clear the instance-stop flag file")
    ap.add_argument("--log", default=None,
                    help="also append checkpoints to this file")
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    if args.flag:
        log("flag file: %r" % read_flag())
        remove_flag()
        return 0
    if args.stop:
        set_flag("stop requested")
        log("STOP flag set at %s" % FLAG_FILE)
        return 0

    if args.once:
        ck = check_once(symbol=args.symbol, log_file=args.log)
        print_report(ck)
        return 0

    if args.cpu:
        log("continuous tick every %ss (stop with --stop flag or Ctrl+C)"
            % args.interval)
        try:
            while True:
                try:
                    ck = check_once(symbol=args.symbol, log_file=args.log)
                    print_report(ck)
                except Exception as e:
                    log("pass failed (will retry): %s" % e)
                if read_flag():
                    log("stop flag seen -- exiting")
                    remove_flag()
                    return 0
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("stopped by user")
            return 0

    log("usage: --once | --cpu [--interval N] | --stop | --flag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
