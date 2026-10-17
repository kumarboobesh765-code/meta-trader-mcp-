r"""Weekly champion-verdict refresh for the FTTest forward test.

1. Reruns the trailing-vs-fixed verdict matrix (backtest_trailing_check.py)
   on fresh 30d data, in-process.
2. Diffs the new WINNER table against the one live in forward_test.py.
3. Reports any verdict FLIPS via Telegram; if flips exist, patches the
   WINNER dict in the VPS copy of forward_test.py and restarts the runner
   (restart_runner.bat) so the new champions take effect.

Runs ON THE VPS. Schedule weekly (e.g. Saturday 12:10 server time, market
closed so fresh data is final and a runner restart is harmless):
  schtasks /TN FTVerdict /TR "C:\Program Files\Python314\python.exe
    C:\FTTest\scripts\weekly_verdict_refresh.py" /SC WEEKLY /D SAT /ST 12:10
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_PATH = r"C:\FTTest\scripts\forward_test.py"
RESTART_BAT = r"C:\FTTest\scripts\restart_runner.bat"
LOG = r"C:\FTTest\logs\weekly_verdict_refresh.log"
MONITOR_TOKEN = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
# XAU-ONLY RIG (2026-09-28): the weekly trail-vs-fixed verdict matrix only
# refreshes XAUUSD champions now that the FX book is retired.
SYMBOLS = ["XAUUSD"]


def tlog(msg):
    print(msg, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(__import__("datetime").datetime.now().isoformat() + " " + msg + "\n")
    except OSError:
        pass


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (MONITOR_TOKEN, CHAT_ID, text.replace("'", "")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def compute_new_verdicts():
    """Run the matrix in-process; return {(sym, strat): 'trail'|'fixed'}."""
    import MetaTrader5 as mt5
    from forward_test import (atr, closed_bars, strat_breakout, strat_london,
                              strat_macross, strat_meanrev, strat_smc,
                              strat_squeeze, strat_straddle)
    import backtest_trailing_check as bt

    bt.strat_breakout, bt.strat_macross = strat_breakout, strat_macross
    bt.strat_meanrev, bt.strat_smc = strat_meanrev, strat_smc
    bt.strat_squeeze, bt.strat_straddle = strat_squeeze, strat_straddle
    bt.strat_london = strat_london

    verdicts = {}
    if not mt5.initialize():
        raise RuntimeError("mt5 init failed: %s" % (mt5.last_error(),))
    try:
        for s in SYMBOLS:
            mt5.symbol_select(s, True)
            si = mt5.symbol_info(s)
            if si is None:
                continue
            dpu = (si.trade_tick_value / max(si.trade_tick_size, 1e-9)) * 0.01
            bars = closed_bars(s, "M15", bt.BARS_REQUEST)
            if len(bars) < 400:
                continue
            for name, fn in bt.SIGNAL_FNS.items():
                fixed, _ = bt.run_signal(fn, bars, dpu, False)
                trail, _ = bt.run_signal(fn, bars, dpu, True)
                if fixed or trail:
                    verdicts[(s, name)] = "trail" if sum(trail) > sum(fixed) else "fixed"
            for name in bt.DUAL_MODES:
                fixed, _ = bt.run_dual(bars, dpu, bt.DUAL_MODES[name], False)
                trail, _ = bt.run_dual(bars, dpu, bt.DUAL_MODES[name], True)
                if fixed or trail:
                    verdicts[(s, name)] = "trail" if sum(trail) > sum(fixed) else "fixed"
    finally:
        mt5.shutdown()
    return verdicts


def parse_winner_block(src):
    m = re.search(r"WINNER = \{(.*?)\n\}", src, re.S)
    if not m:
        raise RuntimeError("WINNER block not found in runner")
    return {(a, b): c for a, b, c in
            re.findall(r'\("([^"]+)",\s*"([^"]+)"\):\s*"(trail|fixed)"', m.group(1))}, m


def main():
    tlog("weekly verdict refresh starting")
    try:
        new = compute_new_verdicts()
    except Exception as e:
        tlog("matrix run failed: %r" % e)
        send_telegram("FTVerdict: matrix run FAILED (%s)" % str(e)[:80])
        return 1

    src = open(RUNNER_PATH, encoding="utf-8").read()
    cur, m = parse_winner_block(src)

    flips = []
    for key in sorted(new):
        old = cur.get(key)
        if old and old != new[key]:
            flips.append((key, old, new[key]))
        elif old is None:
            flips.append((key, "MISSING", new[key]))

    if not flips:
        tlog("no verdict flips (%d slots unchanged)" % len(new))
        send_telegram("FTVerdict: no changes this week (%d slots checked)." % len(new))
        return 0

    # patch the WINNER dict in the VPS runner
    lines = ["WINNER = {"]
    for (s, name) in sorted(new):
        lines.append('    ("%s", "%s"): "%s",' % (s, name, new[(s, name)]))
    lines.append("}")
    src2 = src[:m.start()] + "\n".join(lines) + src[m.end():]
    tmp = RUNNER_PATH + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src2)
    chk = subprocess.run([sys.executable, "-m", "py_compile", tmp],
                         capture_output=True)
    if chk.returncode != 0:
        tlog("patched runner failed py_compile; NOT deploying")
        send_telegram("FTVerdict: flips found but patch failed compile; "
                      "runner NOT changed. Flips: %d" % len(flips))
        os.remove(tmp)
        return 1
    os.replace(tmp, RUNNER_PATH)

    subprocess.run(["cmd", "/c", RESTART_BAT], capture_output=True)
    msg = "FTVerdict: %d flips, runner patched+restarted. " % len(flips)
    msg += "; ".join("%s/%s %s->%s" % (k[0][:3], k[1], o, n) for k, o, n in flips[:6])
    tlog(msg)
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
