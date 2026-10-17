"""Ad-hoc: liquiditysweep reconciliation across windows.

The deployed port (chart38, FT_LIQUIDITYSWEEP) runs the CODE DEFAULTS
(48, 0.20, 0.05) -- no InpLS* inputs in the profile -- chosen per the core
comment "90d fixed +$433". The dashboard shows +$88.80 "60d sweep (port)".
This script re-runs the deployed config and the script's demo anchor
(30, 0.30, 0.05) at 90/60/30d so we can see which number (if any) the
dashboard's edge came from, and whether the deployed config still holds.

Runs ON THE VPS. Read-only.
"""
import sys

sys.path.insert(0, "C:/FTTest/scripts")

import MetaTrader5 as mt5

import backtest_liquiditysweep as bls
from backtest_aetherflow import tr_series
from forward_test import closed_bars, load_env

CONFIGS = [
    ("deployed (48, 0.20, 0.05)", 48, 0.20, 0.05, False),
    ("anchor   (30, 0.30, 0.05)", 30, 0.30, 0.05, False),
]


def main():
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
    cost = 0.20 * dpu + 0.04
    bars = closed_bars("XAUUSD", "H4", bls.FETCH_DAYS * bls.BPD + 300)
    mt5.shutdown()
    trs = tr_series(bars)

    print("XAUUSD liquiditysweep reconciliation (cost $%.2f/trade)" % cost)
    print("%-27s %6s %18s %18s" % ("CONFIG", "days", "FIXED n/net", "TRAIL n/net"))
    for label, lb, wr, buf, rdir in CONFIGS:
        for days in (90, 60, 30, 14):
            t0 = bars[-1]["time"] - days * 86400
            sigs = bls.sweep_signals(bars, trs, lb, wr, buf, t0, rdir)
            f = bls.run_strategy(bars, trs, dpu, cost, sigs, False)
            t = bls.run_strategy(bars, trs, dpu, cost, sigs, True)
            print("%-27s %6d %9d %+8.2f %9d %+8.2f"
                  % (label, days, len(f), sum(f), len(t), sum(t)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
