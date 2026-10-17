r"""Champion-compliance check for the FTTest forward test.

Verifies, live, that every strategy-pair slot behaves per its champion exit
style (forward_test.py WINNER):
  - 'trail' slots: trailing twins hold a SL that ratchets toward price
    (at/above entry for buys after activation) -- or are simply flat
  - 'fixed' slots: trailing twins still hold their ORIGINAL static SL
  - order failures in the runner log since the last check
  - AetherFlow (charts 17-20): per-magic journal trail-modify counts
    (last 2 days) + twin parity from deals.csv (same entries on both twins)

Runs ON THE VPS. Schedule it on trading days shortly after the open:
  schtasks /TN FTCheck /TR "C:\Program Files\Python314\python.exe
    C:\FTTest\scripts\champion_check.py" /SC WEEKLY /D MON,TUE,WED,THU,FRI
    /ST 12:05   (12:05 server time = 09:05 UTC, gold open 10:00 server)

Telegram: reuses the DPAPI-encrypted bot token from the VPS monitor.
"""

import csv
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from forward_test import STRATS, SYMBOLS, STRAT_NAMES, WINNER, load_env

# EA-only rig: the compliance check must look at EA positions, not the old
# runner magics. XAU-ONLY RIG (2026-09-28): the FX book (FTTestMultiEA on
# chart 15, bases 931000-934000) was retired -- only XAUUSD remains.
EA_BASE = {"XAUUSD": 930000}
# chart23-24: order flow (XAUUSD-only, strategy index 9 on the 930000 base).
# The -T twin trails: its A/B is still open.
# chart25-28: trendpullback (idx 10) + donchian (idx 11), added 2026-09-28
# after backtest_new_candidates.py verdicts; both trail-champions on XAU.
# chart29-32: trend (idx 12) + supres (idx 13), added 2026-09-29.
# chart35-36: supertrend (idx 14), added 2026-09-30 (corrected Pine port).
# profile (idx 8, charts 21-22) RETIRED 2026-09-30 -- worst PF family
# (PF 0.33); meanrev (idx 2) also retired -- it lives in STRAT_NAMES and is
# skipped below via RETIRED_STRATS.
RETIRED_STRATS = frozenset(("profile", "meanrev", "trendpullback"))
EXTRA_XAU = (("fixfade", 9),
             ("donchian", 11),
             ("trend", 12), ("vwaprev", 13), ("supertrend", 14),
             ("dayopen", 17))

LOG = r"C:\FTTest\logs\champion_check.log"
MONITOR_TOKEN = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

# --- AetherFlow health (charts 17-20) --------------------------------------
# Magics: 950001/960001 = M15 confluence fixed/trailing,
#         950002/960002 = M30 UT-only fixed/trailing.
# Trail-modify counts come from the MT5 journals (UTF-16), twin parity from
# the runner's deals.csv (the twins must fill the same trades).
AETHER_MAGICS = (950001, 960001, 950002, 960002, 950003, 960003)
AETHER_DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
               r"\D0E8209F77C8CF37AD8BF550E51FF075")
DEALS_CSV = r"C:\FTTest\logs\forward\deals.csv"


def aether_journal_stats(days=2):
    """{magic: {open, trail, close}} parsed from MT5 terminal/Experts journals
    (same evidence as _diag_aetherflow.py section B)."""
    stats = {m: {"open": 0, "trail": 0, "close": 0} for m in AETHER_MAGICS}
    now = time.time()
    journals = (glob.glob(os.path.join(AETHER_DATA, "logs", "*.log"))
                + glob.glob(os.path.join(AETHER_DATA, "MQL5", "Logs", "*.log")))
    for j in journals:
        if now - os.path.getmtime(j) > days * 86400:
            continue
        try:
            txt = open(j, "rb").read().decode("utf-16", errors="replace")
        except OSError:
            continue
        for line in txt.splitlines():
            mm = re.search(r"\b(950001|960001|950002|960002)\b", line)
            if not mm:
                continue
            s = stats[int(mm.group(1))]
            if "trail SL ->" in line:
                s["trail"] += 1
            elif " OPEN " in line:
                s["open"] += 1
            elif " CLOSE " in line:
                s["close"] += 1
    return stats


def aether_twin_parity(max_price_diff=0.10, max_sec_diff=120):
    """Pair each twin set's entry deals in time order (950001<->960001 and
    950002<->960002) and check they filled the same trades: same side,
    price within $0.10, fills within 2 minutes of each other.
    Returns (n_matched, [mismatch strings])."""
    ins = {m: [] for m in AETHER_MAGICS}
    try:
        with open(DEALS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    m = int(row.get("magic", "0"))
                except ValueError:
                    continue
                if m in ins and row.get("entry") == "in":
                    ins[m].append(row)
    except OSError as e:
        return 0, ["deals.csv unreadable: %r" % e]
    for m in ins:
        ins[m].sort(key=lambda r: (r.get("time_utc", ""), r.get("ticket", "")))
    ok, bad = 0, []
    for fixed, trail in ((950001, 960001), (950002, 960002)):
        a_rows, b_rows = ins[fixed], ins[trail]
        if not a_rows and not b_rows:
            continue
        if len(a_rows) != len(b_rows):
            bad.append("%d/%d entry count %d vs %d"
                       % (fixed, trail, len(a_rows), len(b_rows)))
        for i, (a, b) in enumerate(zip(a_rows, b_rows)):
            try:
                dsec = abs((datetime.fromisoformat(a["time_utc"])
                            - datetime.fromisoformat(b["time_utc"])).total_seconds())
                dprice = abs(float(a["price"]) - float(b["price"]))
            except (KeyError, ValueError):
                dsec = dprice = 1e9
            if (a.get("type") == b.get("type")
                    and dprice <= max_price_diff and dsec <= max_sec_diff):
                ok += 1
            else:
                bad.append("%d/%d trade#%d %s/%s dP=%.2f dT=%.0fs"
                           % (fixed, trail, i + 1, a.get("type"), b.get("type"),
                              dprice, dsec))
    return ok, bad


def tlog(msg):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(datetime.now().isoformat() + " " + msg + "\n")
    except OSError:
        pass


def send_telegram(text):
    """Fire-and-forget Telegram alert using the monitor's DPAPI token."""
    try:
        import ctypes.wintypes as wt
        import ctypes
        blob = open(MONITOR_TOKEN, "rb").read().strip().decode()
        # monitor stores the token DPAPI-encrypted as a base64 SecureString;
        # simplest reliable path: let PowerShell decrypt it
        ps = ("$t=(Get-Content '%s' -Raw).Trim();"
              "$s=ConvertTo-SecureString $t;"
              "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
              "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
              "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
              " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
              % (MONITOR_TOKEN, CHAT_ID, text.replace("'", "")))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    except Exception as e:
        tlog("telegram send failed: %r" % e)


def streams():
    """[(symbol, strat, base_magic, twin_magic, champion)] for the XAU EA slots."""
    out = []
    for sym in EA_BASE:   # XAU-only rig: EA_BASE drives the symbol list
        base0 = EA_BASE[sym]
        for i, name in enumerate(STRAT_NAMES, start=1):
            if name in RETIRED_STRATS:
                continue  # retired 2026-09-30 (charts 3/4): magics stay logged
            champ = WINNER.get((sym, name), "trail")
            out.append((sym, name, base0 + i, base0 + 10000 + i, champ))
    for name, i in EXTRA_XAU:
        out.append(("XAUUSD", name, EA_BASE["XAUUSD"] + i,
                    EA_BASE["XAUUSD"] + 10000 + i, "trail"))
    # FX streams removed 2026-09-28 (XAU-only rig): FTTestMultiEA chart15
    # retired, FX magics 931000-934000 no longer traded or checked.
    return out


def main():
    env = load_env()
    if not mt5.initialize():
        tlog("mt5.initialize failed: %s" % (mt5.last_error(),))
        send_telegram("FTCheck: mt5 init failed")
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        return 1
    tlog("champion check on %s" % acc.server)

    problems, notes = [], []
    n_trail_open = n_fixed_open = n_flat = 0
    for sym, name, base_m, twin_m, champ in streams():
        poss = [p for p in (mt5.positions_get(symbol=sym) or [])
                if p.magic in (base_m, twin_m)]
        if not poss:
            n_flat += 1
            continue
        for p in poss:
            is_twin = (p.magic == twin_m)
            label = "%s %s%s" % (sym, name, "-T" if is_twin else "")
            if not is_twin:
                continue  # fixed twins are always static by construction
            if champ == "trail":
                # evidence of a moved SL: SL on the profit side of entry
                entry = p.price_open
                moved = (p.sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < p.sl < entry)
                if moved:
                    n_trail_open += 1
                else:
                    notes.append("%s flat-open, no ratchet yet (ok if young)"
                                 % label)
            else:
                # fixed champion: SL must still be the ORIGINAL stop.
                # original SL distance == 2*ATR for signals; detect any SL that
                # sits on the profit side of entry (a static SL never does).
                entry = p.price_open
                bad = (p.sl > entry) if p.type == mt5.POSITION_TYPE_BUY \
                    else (0 < p.sl < entry)
                if bad:
                    problems.append("%s is 'fixed' champion but SL moved past "
                                    "entry (sl=%.5f entry=%.5f)"
                                    % (label, p.sl, entry))
                else:
                    n_fixed_open += 1

    # order failures in the runner log since the last check marker
    fails = 0
    log_path = r"C:\FTTest\logs\forward_test_stdout.txt"
    try:
        marker_path = r"C:\FTTest\logs\champion_check.marker"
        last_pos = 0
        if os.path.exists(marker_path):
            last_pos = int(open(marker_path).read().strip() or 0)
        size = os.path.getsize(log_path)
        with open(log_path, errors="replace") as f:
            if last_pos:
                f.seek(min(last_pos, size))
            chunk = f.read()
        with open(marker_path, "w") as f:
            f.write(str(size))
        fails = chunk.count("FAILED retcode=")
        loop_errs = chunk.count("loop error")
    except OSError as e:
        tlog("runner log read failed: %r" % e)
        fails = loop_errs = -1

    msg = ("FTCheck: %d trail-managed, %d fixed-managed, %d flat. "
           "order-fails=%d loop-errors=%d" % (n_trail_open, n_fixed_open, n_flat,
                                              fails, loop_errs))

    # AetherFlow health (charts 17-20): journal trail-modify counts + twin
    # parity from deals.csv. A trailing twin with opens but zero trail-mods
    # over days while holding a gain is the failure signature; parity flags
    # one twin trading while the other didn't.
    try:
        st = aether_journal_stats()
        n_match, parity_bad = aether_twin_parity()
        msg += " aether:"
        for m in AETHER_MAGICS:
            msg += " %d(o%d/t%d/c%d)" % (m, st[m]["open"], st[m]["trail"],
                                          st[m]["close"])
        msg += " parity=%dOK" % n_match
        if parity_bad:
            msg += " PARITY: " + "; ".join(parity_bad[:3])
            tlog("aether parity: " + "; ".join(parity_bad))
    except Exception as e:
        msg += " aether check error %r" % e
        tlog("aether check error: %r" % e)

    if problems:
        msg += " PROBLEMS: " + "; ".join(problems[:4])
        tlog("PROBLEMS: " + "; ".join(problems))
    send_telegram(msg)
    tlog(msg)
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
