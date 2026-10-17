r"""Weekly: rerun the trail sweep and report drift from deployed values.

Answers (2026-10-01 request): "schedule the trail sweep to rerun weekly and
report when any family's optimal config drifts from deployed values."

Runs the m15 + other-host sections of backtest_trail_full_sweep.py (SMVP
excluded: its trail variants were noise-level), parses each family's best
config, and compares against the DEPLOYED map. A DRIFT is reported when the
best config differs from deployed by more than $20/30d-equivalent.

Output: C:/FTTest/logs/trail_drift_weekly.txt (overwritten each run).

Usage (scheduled Mon 06:30 VPS):
  python -u C:/FTTest/scripts/_trail_drift_weekly.py
"""
import contextlib
import io
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

import backtest_trail_full_sweep as btsf
from forward_test import load_env

DEPLOYED = {
    # FTTest twins -> tightest per the 2026-10-01 sweep. Only families whose
    # -T twin actually TRAILS belong here: meanrev/trendpullback retired,
    # london's twin runs trailing=false (fixed won the 10/01 backtest), and
    # fixfade/vwaprev ride backtest_institutional engines, not this sweep.
    "breakout": "tightest 0.10/0.3/0.05",
    "macross": "tightest 0.10/0.3/0.05",
    "smc": "tightest 0.10/0.3/0.05",
    "squeeze": "tightest 0.10/0.3/0.05",
    "straddle": "tightest 0.10/0.3/0.05",
    "trend": "tightest 0.10/0.3/0.05",
    # special cases from the same sweep
    "aetherflow-M30": "fttest 0.2/0.5/0.10",
    "aetherflow-H4": "live 0.8/1.0/0.25",
    "supertrend-H1": "tight 0.5/0.8/0.20",
    "liquiditysweep-H4": "fttest 0.2/0.5/0.10",
}
DRIFT_USD = 20.0

# which config list each table family used (must mirror
# backtest_trail_full_sweep.FT_CONFIGS / AE_CONFIGS order)
AE_FAMILIES = {"aetherflow-M30", "aetherflow-H4", "supertrend-H1",
               "liquiditysweep-H4"}


def parse_nets(txt, ft_configs, ae_configs):
    """Parse the sweep tables -> {family: {config_tag: net_30d}}."""
    nets = {}
    section = None
    for line in txt.splitlines():
        if line.startswith("== M15-host twins"):
            section = ft_configs
            continue
        if line.startswith("== other-host twins"):
            section = ae_configs
            continue
        if line.startswith("=="):
            section = None
            continue
        if section is None:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 1 + len(section):
            continue
        m = re.match(r"(\S+)\s+([+-][\d.]+)$", parts[0])
        if not m:
            continue
        fam = m.group(1)
        cells = {}
        okrow = True
        for tag, cell in zip([c[3] for c in section], parts[1:]):
            mc = re.match(r"([+-][\d.]+)/\d+", cell)
            if not mc:
                okrow = False
                break
            cells[tag] = float(mc.group(1))
        if okrow:
            nets[fam] = cells
    return nets


def main():
    load_env()
    ok = False
    for _ in range(5):
        if mt5.initialize():
            ok = True
            break
        mt5.shutdown()
        import time as _t
        _t.sleep(10)
    if not ok:
        print("mt5.initialize failed")
        return 1
    acc = mt5.account_info()
    si = mt5.symbol_info("XAUUSD")
    dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
    cost = 0.20 * dpu + 0.04

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        btsf.run_m15_section(dpu)
        btsf.run_hosts_section(dpu, cost)
    mt5.shutdown()

    nets = parse_nets(buf.getvalue(), btsf.FT_CONFIGS, btsf.AE_CONFIGS)
    lines = ["trail drift report %s (VPS)" %
             datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
    drifts = []
    for name in sorted(DEPLOYED):
        dep = DEPLOYED[name]
        cells = nets.get(name)
        if not cells or dep not in cells:
            lines.append("  %-18s NOT MEASURED this week (no events?) | deployed %s"
                         % (name, dep))
            continue
        best_tag = max(cells, key=lambda t: cells[t])
        delta = cells[best_tag] - cells[dep]
        if best_tag != dep and delta > DRIFT_USD:
            lines.append("  %-18s DRIFT: best %s beats deployed %s by $%.0f"
                         % (name, best_tag, dep, delta))
            drifts.append(name)
        else:
            lines.append("  %-18s stable | deployed %s (best-vs-deployed %+0.0f)"
                         % (name, dep, delta))
    lines.append("")
    lines.append("drifts: %s" % (", ".join(drifts) if drifts else "none"))
    txt = "\n".join(lines)
    print(txt)
    with open("C:/FTTest/logs/trail_drift_weekly.txt", "w") as fh:
        fh.write(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
