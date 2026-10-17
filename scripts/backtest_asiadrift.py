r"""Backtest: server-label 01:00 gold drift ("Asian-session" finding, corrected).

Pattern (2026-10-01 scan, 180d M15): label hour 01:00 is the ONLY hour with
significant directional drift: +0.078 ATR/bar, z~2.1, n=752. EVERYTHING ELSE
noise. TZ PROBE RESULT: MT5 labels are UTC+3, so label 01:00 = real 22:00 UTC
(late-US), NOT Asia. True Tokyo hours = labels 03:00-09:00. Stage 0 below
re-prints the drift table with the honest mapping before anything is traded.

Session reality: Vantage gold is CLOSED ~00:00-01:05 server -> the 00:45
signal bar does not exist. A live EA can only enter at the FIRST bar of the
server day, which is exactly what we replay: signal = last closed bar of the
prior server day -> LONG at the next bar's open (first tradeable minute).

House replay rules: next-open entry, SL checked before TP inside a bar
(pessimistic), time exit at bar close, cost $0.24/trade (0.20*dpu spread +
0.04 RT), ATR(96, M15) frozen at entry.

Grid:
  hold   2 / 4 / 8 / 16 bars (30m / 1h / 2h / 4h)
  SL     1.0 / 1.5 / 2.0 / 3.0 ATR
  TP     none (pure drift) / 0.5 / 1.0 ATR
  filter all days / low-vol only (ATR(96) <= its 30d median -> finding #3)
  twin   fixed exit vs ratcheting trail (0.10/0.3/0.05)

Decision: survive = net>0 on 180d AND 90d AND 30d, avg/trip > $0.10,
no single day > 25% of net. Port decision printed at the end.

Usage: python backtest_asiadrift.py [--days 180]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from forward_test import closed_bars, load_env

COST = None          # set in main: 0.20 * dpu + 0.04
DPU = None
HOLDS = (2, 4, 8, 16)
SLS = (1.0, 1.5, 2.0, 3.0)
TPS = (None, 0.5, 1.0)
TRAIL = (0.10, 0.30, 0.05)   # twin trail candidate (tightest FT config)

OUT = []


def emit(s=""):
    print(s)
    OUT.append(s)


def atr96(bars):
    """Rolling ATR(96) SMA-of-TR, index-aligned, None until warm."""
    trs, pc = [], None
    for b in bars:
        ref = pc if pc is not None else b["close"]
        trs.append(max(b["high"] - b["low"],
                       abs(b["high"] - ref), abs(b["low"] - ref)))
        pc = b["close"]
    out = [None] * len(trs)
    s = 0.0
    for i, tr in enumerate(trs):
        s += tr
        if i >= 96:
            s -= trs[i - 96]
        if i >= 95:
            out[i] = s / 96.0
    return out


def day_first_signals(bars):
    """Indexes of each server-day's LAST bar -> enter at next bar open."""
    idx = []
    for i in range(len(bars) - 1):
        if bars[i]["time"] // 86400 != bars[i + 1]["time"] // 86400:
            idx.append(i)
    return idx


def signal_at(bars, hh, mm):
    """Indexes of label hh:mm bars (signal on close -> enter next bar open)."""
    idx = []
    for i, b in enumerate(bars):
        t = b["time"] % 86400
        if (t // 3600) == hh and (t % 3600) == mm * 60:
            idx.append(i)
    return idx


def stage0_drift_table(bars, a):
    """Per-label-hour per-bar drift in ATR units with honest UTC mapping."""
    import math
    rows = []
    for h in range(24):
        rets = []
        for i in range(1, len(bars)):
            b, p = bars[i], bars[i - 1]
            if a[i] is None or a[i - 1] is None:
                continue
            if (b["time"] % 86400) // 3600 != h or (p["time"] % 86400) // 3600 != h:
                continue
            rets.append((b["close"] - b["open"]) / a[i])
        if len(rets) < 100:
            continue
        n = len(rets)
        mean = sum(rets) / n
        var = sum((x - mean) ** 2 for x in rets) / max(n - 1, 1)
        z = mean / math.sqrt(var / n) if var > 0 else 0.0
        rows.append((abs(z), h, mean, z, n))
    rows.sort(reverse=True)
    emit("STAGE 0 -- per-label-hour M15 drift (ATR/bar), honest UTC = label-3:")
    emit("%-14s %10s %7s %7s" % ("label hr (UTC)", "ATR/bar", "z", "n"))
    for _, h, mean, z, n in rows[:6]:
        emit("  %02d:00 (%02d:00)   %+0.4f   %+5.2f %5d"
             % (h, (h - 3) % 24, mean, z, n))
    emit("")


def run_one(bars, a, sigs, hold, sl_atr, tp_atr, lowvol_only, trailing,
            side="long"):
    """Returns list of trade P&L ($) and list of (day, pnl) for diagnostics."""
    trades = []
    by_day = {}
    sgn = 1.0 if side == "long" else -1.0
    for i in sigs:
        if i + 1 >= len(bars) or a[i] is None:
            continue
        if lowvol_only:
            win = [x for x in a[max(0, i - 30 * 96):i + 1] if x is not None]
            if not win or a[i] > sorted(win)[len(win) // 2]:
                continue                       # high-vol regime -> skip
        e = bars[i + 1]["open"]
        sl = e - sgn * sl_atr * a[i]
        tp = None if tp_atr is None else e + sgn * tp_atr * a[i]
        stop = sl
        act = e + sgn * TRAIL[0] * a[i] if trailing else None
        exit_px = None
        for j in range(i + 1, min(i + 1 + hold, len(bars))):
            b = bars[j]
            hit_sl = b["low"] <= stop if side == "long" else b["high"] >= stop
            hit_tp = (tp is not None and
                      (b["high"] >= tp if side == "long" else b["low"] <= tp))
            if hit_sl:                         # pessimistic: SL first
                exit_px = stop
                break
            if hit_tp:
                exit_px = tp
                break
            if trailing:
                hit_act = (b["high"] >= act if side == "long"
                           else b["low"] <= act)
                if hit_act:
                    stop = (max(stop, b["close"] - TRAIL[1] * a[i])
                            if side == "long"
                            else min(stop, b["close"] + TRAIL[1] * a[i]))
                    act = b["close"] + sgn * TRAIL[0] * a[i]
            if j == i + hold:                  # time exit at bar close
                exit_px = b["close"]
        if exit_px is None:                    # ran out of bars
            exit_px = bars[-1]["close"]
        pnl = sgn * (exit_px - e) * DPU - COST
        trades.append(pnl)
        day = bars[i + 1]["time"] // 86400
        by_day[day] = by_day.get(day, 0.0) + pnl
    return trades, by_day


def stats(trades, by_day):
    n = len(trades)
    net = sum(trades)
    wins = sum(1 for x in trades if x > 0)
    gp = sum(x for x in trades if x > 0)
    gl = -sum(x for x in trades if x < 0)
    pf = ("%.2f" % (gp / gl)) if gl > 1e-9 else ("inf" if gp > 0 else "-")
    worst_day_share = 0.0
    if by_day and net > 0:
        wd = min(by_day.values())
        worst_day_share = -wd / net if wd < 0 else 0.0
    return {"n": n, "net": net, "avg": net / n if n else 0.0,
            "win%": 100.0 * wins / n if n else 0.0, "pf": pf,
            "wd_share": worst_day_share}


def main():
    global COST, DPU
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    args = ap.parse_args()

    load_env()
    if not mt5.initialize():
        print("mt5 attach failed")
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    DPU = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    COST = 0.20 * DPU + 0.04
    bars = closed_bars("XAUUSD", "M15", args.days * 96 + 200)
    mt5.shutdown()
    emit("asia-drift backtest %s | %d M15 bars | dpu=%.2f cost=%.2f/trade"
         % (acc.login, len(bars), DPU, COST))

    a = atr96(bars)
    sigs = day_first_signals(bars)
    emit("signal days: %d (prior-day last bar -> day-first open entry)"
         % len(sigs))
    if sigs:
        gaps = [(bars[i + 1]["time"] - bars[i]["time"]) / 3600.0 for i in sigs]
        emit("entry gaps: min %.1fh max %.1fh (weekend entries included)"
             % (min(gaps), max(gaps)))
    stage0_drift_table(bars, a)

    # windows for robustness: last 180 / 90 / 30 days of signal bars
    def sigs_since(sigs, days):
        if not sigs:
            return []
        t0 = bars[sigs[-1]]["time"] - days * 86400
        return [i for i in sigs if bars[i]["time"] >= t0]

    MODES = (
        ("dayopen-LONG", day_first_signals(bars), "long"),
        ("ctrl11-LONG", signal_at(bars, 10, 45), "long"),
        ("ctrl18-LONG", signal_at(bars, 17, 45), "long"),
        ("ldn09-SHORT", signal_at(bars, 11, 45), "short"),
    )
    best_by_mode = {}
    for name, sigs, side in MODES:
        rows = []
        for hold in HOLDS:
            for sl_atr in SLS:
                for tp_atr in TPS:
                    for lv in (False, True):
                        for tr in (False, True):
                            trs, byd = run_one(bars, a, sigs, hold, sl_atr,
                                               tp_atr, lv, tr, side)
                            st = stats(trs, byd)
                            if st["n"] < 20:
                                continue
                            st90 = stats(*run_one(bars, a, sigs_since(sigs, 90),
                                                  hold, sl_atr, tp_atr, lv,
                                                  tr, side))
                            st30 = stats(*run_one(bars, a, sigs_since(sigs, 30),
                                                  hold, sl_atr, tp_atr, lv,
                                                  tr, side))
                            survive = (st["net"] > 0 and st90["net"] > 0
                                       and st30["net"] > 0
                                       and st["avg"] > 0.10
                                       and st["wd_share"] < 0.25)
                            rows.append((st["net"], hold, sl_atr, tp_atr, lv,
                                         tr, st, st90, st30, survive))
        rows.sort(reverse=True)
        best_by_mode[name] = rows
        emit("")
        emit("== MODE %s (%d signals) ==" % (name, len(sigs)))
        emit("%-26s %7s %7s %6s %5s %5s  %-18s %-18s %s"
             % ("CONFIG", "net", "avg/tr", "win%", "PF", "wd%",
                "net90 (avg)", "net30 (avg)", "SURVIVE"))
        for net, hold, sl_atr, tp_atr, lv, tr, st, st90, st30, survive in rows[:8]:
            tp_s = "-" if tp_atr is None else "%.1f" % tp_atr
            cfg = "h%d SL%.1f TP%s %s%s" % (hold, sl_atr, tp_s,
                                            "lv " if lv else "",
                                            "trail" if tr else "fix")
            emit("%-26s %+7.2f %+7.2f %5.0f%% %5s %5.0f  %+6.2f (%+.2f)  %+6.2f (%+.2f)  %s"
                 % (cfg, st["net"], st["avg"], st["win%"], st["pf"],
                    100 * st["wd_share"], st90["net"], st90["avg"],
                    st30["net"], st30["avg"], "YES" if survive else ""))

    # matched-config beta test: dayopen vs fixed-time long entries
    emit("")
    emit("== BETA CONTROL (matched configs, 180d net) ==")
    margins = []
    for net, hold, sl_atr, tp_atr, lv, tr, st, st90, st30, _ \
            in best_by_mode["dayopen-LONG"][:5]:
        tp_s = "-" if tp_atr is None else "%.1f" % tp_atr
        cfg = (hold, sl_atr, tp_atr, lv, tr)
        n11 = next((r[0] for r in best_by_mode["ctrl11-LONG"]
                    if (r[1], r[2], r[3], r[4], r[5]) == cfg), None)
        n18 = next((r[0] for r in best_by_mode["ctrl18-LONG"]
                    if (r[1], r[2], r[3], r[4], r[5]) == cfg), None)
        ctrls = [x for x in (n11, n18) if x is not None]
        cmax = max(ctrls) if ctrls else float("nan")
        margins.append(net - cmax)
        emit("h%d SL%.1f TP%s %s%s: dayopen %+8.2f | ctrl11 %+8.2f | ctrl18 %+8.2f | margin %+7.2f"
             % (hold, sl_atr, tp_s, "lv " if lv else "",
                "trail" if tr else "fix", net,
                n11 if n11 is not None else float("nan"),
                n18 if n18 is not None else float("nan"), net - cmax))
    med_margin = sorted(margins)[len(margins) // 2] if margins else -1e9

    # weekend split on the top dayopen config (h16 SL2.0 no-TP fixed)
    emit("")
    emit("== DAY SPLIT (dayopen h16 SL2.0 TP- fix) ==")
    base = day_first_signals(bars)
    for label, keep in (("all days", None),
                        ("weekday (gap<=3h)", True),
                        ("Monday (gap>3h)", False)):
        sel = []
        for i in base:
            g = (bars[i + 1]["time"] - bars[i]["time"]) / 3600.0
            if keep is None or ((g <= 3.0) == keep):
                sel.append(i)
        trs, byd = run_one(bars, a, sel, 16, 2.0, None, False, False, "long")
        st = stats(trs, byd)
        emit("%-20s net %+7.2f  avg %+6.2f  n=%3d  win %3.0f%%"
             % (label, st["net"], st["avg"], st["n"], st["win%"]))

    def best_surviving(name):
        for r in best_by_mode[name]:
            if r[-1]:
                return r
        return None

    emit("")
    do = best_surviving("dayopen-LONG")
    if do is None:
        emit("VERDICT dayopen LONG: REJECT -- no config survives all windows")
    elif med_margin > 100:
        net, hold, sl_atr, tp_atr, lv, tr, st, st90, st30, _ = do
        tp_s = "-" if tp_atr is None else "%.1f" % tp_atr
        emit("VERDICT dayopen LONG: PORT -- survives windows AND beats beta"
             " controls (median margin %+.2f): h%d SL%.1f TP%s %s"
             % (med_margin, hold, sl_atr, tp_s, "trail" if tr else "fixed"))
    else:
        emit("VERDICT dayopen LONG: REJECT as pattern -- P&L positive but not"
             " separable from gold trend beta (median margin %+.2f)"
             % med_margin)
    sh = best_surviving("ldn09-SHORT")
    if sh:
        net, hold, sl_atr, tp_atr, lv, tr, st, st90, st30, _ = sh
        tp_s = "-" if tp_atr is None else "%.1f" % tp_atr
        emit("VERDICT ldn09-SHORT: candidate -- h%d SL%.1f TP%s %s net %+7.2f"
             " (90d %+7.2f / 30d %+7.2f, PF %s)"
             % (hold, sl_atr, tp_s, "trail" if tr else "fixed", net,
                st90["net"], st30["net"], st["pf"]))
    else:
        emit("VERDICT ldn09-SHORT: no config survives all windows")
    with open("C:/FTTest/logs/asia_drift_bt.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
