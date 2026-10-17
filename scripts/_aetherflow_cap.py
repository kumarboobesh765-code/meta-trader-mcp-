"""Ad-hoc: does a TIME CAP help the aetherflow H4 edge? (parity evidence)

Context: the live aetherflow-H4 twins (950003 fixed / 960003 trail) hold a
29h short opened at 4145 while price ran to ~4185. The EA has NO time stop
and the backtest (backtest_aetherflow.run_backtest) has none either -- it
exits on SL/TP/trail only. So adding a cap to the EA is a DEVIATION from
the current backtest; the only justification is that the cap IMPROVES the
measured edge. This probe:

  1) re-runs the H4 UT backtest exactly as run_backtest does, recording
     per-trade hold duration in bars and pnl
  2) re-runs it with time caps (bars) for fixed and trail twins
  3) prints the cap sweep so the chosen value is evidence-based

H4 = 6 bars/day, so 6 bars = 24h, 8 = 32h, 12 = 48h.

Runs ON THE VPS. Read-only.
"""
import os
import sys

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

import backtest_aetherflow as ba
from forward_test import closed_bars, load_env

CAPS = (0, 4, 6, 8, 10, 12)   # 0 = no cap (parity with run_backtest)


def run_capped(eng, bars, dpu, cost, mode, trailing, cap):
    """run_backtest clone + optional bar cap. Returns (trades, holds)."""
    trades, holds = [], []
    busy_until = -1
    for i in range(ba.WARMUP, eng.n - 2):
        if i <= busy_until:
            continue
        if mode == "ut":
            want_buy, want_sell = eng.ut_buy[i], eng.ut_sell[i]
        else:
            want_buy, want_sell = eng.confluence(i)
        if not want_buy and not want_sell:
            continue
        if want_buy and want_sell:
            continue
        side = "buy" if want_buy else "sell"
        a = ba.sma_atr_at(eng.trs, i)
        if not a:
            continue
        px = bars[i]["close"]
        sl = px - ba.SL_ATR_MULT * a if side == "buy" else px + ba.SL_ATR_MULT * a
        tp = px + ba.TP_ATR_MULT * a if side == "buy" else px - ba.TP_ATR_MULT * a
        nxt = bars[i + 1]
        entry = nxt["open"]
        if (side == "buy" and nxt["low"] <= sl) or \
           (side == "sell" and nxt["high"] >= sl):
            raw = (sl - entry) if side == "buy" else (entry - sl)
            trades.append(raw * dpu - cost)
            holds.append(0)
            busy_until = i + 1
            continue
        if trailing:
            exit_px, exit_i, _m = ba.walk_exit_trail(side, entry, sl, tp, a,
                                                    bars, i + 2)
        else:
            exit_px, exit_i = ba.walk_exit_fixed(side, sl, tp, bars, i + 2)
        # --- the cap: close at the first bar close at/after cap bars held ---
        if cap > 0 and exit_i > i + 1 + cap:
            exit_i = i + 1 + cap
            exit_px = bars[exit_i]["close"]
        raw = (exit_px - entry) if side == "buy" else (entry - exit_px)
        trades.append(raw * dpu - cost)
        holds.append(exit_i - (i + 1))
        busy_until = exit_i
    return trades, holds


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    load_env()
    if not mt5.initialize():
        print("mt5.initialize failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo only")
        mt5.shutdown()
        return 1
    si = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = ba.SPREAD_PRICE.get("XAUUSD", 0.0) * dpu + ba.COMMISSION
    bpd = ba.BARS_PER_DAY.get("H4", 6)   # bt dict has no H4; H4 = 6 bars/day
    bars = closed_bars("XAUUSD", "H4", days * bpd + 300)
    mt5.shutdown()
    eng = ba.Engines(bars)

    print("XAUUSD aetherflow H4 UT, last %dd | SL 2.0 / TP 3.0 ATR | "
          "cost $%.2f | H4 = 6 bars/day" % (days, cost))
    for trailing, label in ((False, "fixed"), (True, "trail")):
        base, holds = run_capped(eng, bars, dpu, cost, "ut", trailing, 0)
        n, net, pf = ba.row(base)
        if holds:
            hs = sorted(holds)
            print("\n%s twin (no cap, = run_backtest parity): n=%d net=%+.2f PF=%s"
                  % (label, n, net, pf))
            print("  hold bars: min=%d med=%d p90=%d max=%d | >=6 bars: %d | "
                  ">=12 bars: %d"
                  % (hs[0], hs[len(hs) // 2], hs[int(len(hs) * 0.9)], hs[-1],
                     sum(1 for h in hs if h >= 6), sum(1 for h in hs if h >= 12)))
            # contribution of long holds
            long_net = sum(t for t, h in zip(base, holds) if h >= 6)
            short_net = sum(t for t, h in zip(base, holds) if h < 6)
            n_long = sum(1 for h in holds if h >= 6)
            print("  held <6 bars: n=%d net=%+.2f (avg %+.2f)"
                  % (len(holds) - n_long, short_net,
                     short_net / max(1, len(holds) - n_long)))
            print("  held >=6 bars: n=%d net=%+.2f (avg %+.2f)"
                  % (n_long, long_net, long_net / max(1, n_long)))
        print("  cap sweep (bars : net / n):")
        for cap in CAPS:
            t, h = run_capped(eng, bars, dpu, cost, "ut", trailing, cap)
            cn, cnet, cpf = ba.row(t)
            print("    %2d : %+8.2f  n=%-3d PF=%s"
                  % (cap, cnet, cn, cpf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
