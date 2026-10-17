r"""AetherFlow M15-confluence porting-drift audit. Runs ON THE VPS.

Replays the EA's exact confluence engine (backtest_aetherflow.Engines, which
is a line-for-line port of AetherFlowEA.mq5 Step* functions) over the SAME
600 closed-bar window the EA uses on every new bar, lists every bar where
wantBuy/wantSell fires, and matches those signals against what the chart-17
EA (950001) and its twin (960001) actually did:

  FILLED             journal OPEN / deals.csv entry within +-180s of bar close
  SKIPPED-BY-DESIGN  signal fired while a same-direction position was open
                     (ActOnSignal holds aligned positions)
  MISSED             no fill and no same-side position  ->  porting drift
  EXTRA FILL         EA opened with NO python-engine signal -> drift (other way)

Optional Pine cross-check: --pine alerts.txt with one signal per line
(flexible: 'YYYY-MM-DDTHH:MM', optionally ' buy|sell|long|short'), e.g. the
alert list exported from the TradingView "Aether Flow" script. Reports
pine-only and engine-only signals within one bar.

Usage: python C:/FTTest/scripts/audit_aetherflow_signals.py [--days N] [--tg]
       [--pine alerts.txt] [--magic 950001]
"""
import argparse
import csv
import glob
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from backtest_aetherflow import Engines, WARMUP
from forward_test import closed_bars, load_env

DATA = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
DEALS_CSV = r"C:\FTTest\logs\forward\deals.csv"
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
SERVER_UTC_OFFSET = 3          # Vantage server time = UTC+3
EA_BARS = 600                  # CopyRates(..., 1, 600) in AetherFlowEA.OnTick
TF_SEC = {"M15": 900, "M30": 1800, "H1": 3600}
FILL_TOLERANCE_S = 180


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def journal_lines(magic, days):
    """[(utc_datetime, line)] of this magic's journal lines. MT5 journal
    lines carry time-of-day only (e.g. 'EL\\t0\\t00:00:00.094\\t<source>\\t...');
    the date comes from the log filename (YYYYMMDD.log)."""
    import time as _t
    out = []
    now = _t.time()
    for j in (glob.glob(os.path.join(DATA, "logs", "*.log"))
              + glob.glob(os.path.join(DATA, "MQL5", "Logs", "*.log"))):
        if now - os.path.getmtime(j) > days * 86400:
            continue
        mfile = re.search(r"(\d{8})\.log$", j)
        if not mfile:                      # skip metaeditor.log etc.
            continue
        day = datetime.strptime(mfile.group(1), "%Y%m%d").date()
        try:
            txt = open(j, "rb").read().decode("utf-16", errors="replace")
        except OSError:
            continue
        for line in txt.splitlines():
            # label is "aetherflow <magic>"; match the bare magic like the
            # proven _diag_aetherflow.py does (journals are tab-separated)
            if not re.search(r"\b%d\b" % magic, line):
                continue
            tm = re.search(r"(\d{2}):(\d{2}):(\d{2})", line)
            if not tm:
                continue
            from datetime import time as dtime
            # MT5 terminal journals are stamped in the VPS LOCAL timezone
            # (not the broker's UTC+3): the 09-27 22:30 UTC M30 open printed
            # as 04:00 local. Subtract the local offset to get true UTC.
            local = datetime.combine(day, dtime(int(tm.group(1)),
                                                int(tm.group(2)),
                                                int(tm.group(3))))
            out.append((local - local.astimezone().utcoffset(), line.strip()))
    return sorted(out)


def deal_entries(magic):
    """deals.csv entry-in rows for one magic, chronologically."""
    rows = []
    try:
        with open(DEALS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("magic") == str(magic) and row.get("entry") == "in":
                    dt = datetime.fromisoformat(row["time_utc"])
                    if dt.tzinfo:
                        dt = dt.replace(tzinfo=None)
                    # the logger stamps broker-server wall clock as "UTC"
                    # (MT5 python epochs encode server-TZ labels); convert
                    # to true UTC so journal/deal times are comparable
                    row = {**row, "_t": dt - timedelta(hours=SERVER_UTC_OFFSET)}
                    rows.append(row)
    except OSError:
        pass
    rows.sort(key=lambda r: r["_t"])
    return rows


def open_intervals(entries):
    """[(t_in, t_out_or_None, side)] from chronological in/out entries."""
    iv, opens = [], {}
    for r in entries:
        pid = r.get("position_id")
        if r.get("entry") == "in":
            opens[pid] = (r["_t"], r.get("type"))
        else:
            o = opens.pop(pid, None)
            if o:
                iv.append((o[0], r["_t"], o[1]))
    for pid, (t_in, side) in opens.items():
        iv.append((t_in, None, side))
    return sorted(iv)


def engine_signals(bars, mode):
    """Every bar (i >= WARMUP) where the EA's decision block fires."""
    eng = Engines(bars)
    sigs = []
    for i in range(WARMUP, eng.n):
        if mode == "ut":
            wb, ws = eng.ut_buy[i], eng.ut_sell[i]
        else:
            wb, ws = eng.confluence(i)
        if not wb and not ws:
            continue
        members = []
        if eng.ut_buy[i]:
            members.append("UT")
        if eng.ut_sell[i]:
            members.append("UT")
        if eng.ext_b[i]:
            members.append("EXT-" + ("CHOC" if eng.ext_kb[i] == 1 else "BOS"))
        if eng.ext_s[i]:
            members.append("EXT-" + ("CHOC" if eng.ext_ks[i] == 1 else "BOS"))
        if eng.int_b[i] or eng.int_s[i]:
            members.append("INT")
        if eng.b3ev[i] or eng.b3cf[i] or eng.s3ev[i] or eng.s3cf[i]:
            members.append("3BR")
        if eng.mom_b[i] or eng.mom_s[i]:
            members.append("MOM")
        sigs.append({"i": i, "side": "BUY" if wb else "SELL",
                     "t_open": bars[i]["time"], "close": bars[i]["close"],
                     "members": "+".join(members) or "?"})
    return sigs


def bar_close_utc(t_open_epoch, tf):
    """Signal acts right after the closed bar's end. Bar epochs are stamped in
    server wall-clock; convert to UTC."""
    utc = datetime.fromtimestamp(t_open_epoch + TF_SEC[tf], tz=timezone.utc)
    return utc.replace(tzinfo=None) - timedelta(hours=SERVER_UTC_OFFSET)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--tf", default="M15", choices=sorted(TF_SEC))
    ap.add_argument("--mode", default="confluence", choices=("confluence", "ut"))
    ap.add_argument("--magic", type=int, default=950001,
                    help="fixed twin whose journal/deals are audited")
    ap.add_argument("--days", type=int, default=7, help="journal lookback")
    ap.add_argument("--pine", default=None,
                    help="optional TradingView alert list (one per line)")
    ap.add_argument("--tg", action="store_true")
    args = ap.parse_args()

    env = load_env()
    if not mt5.initialize():
        print("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print("REFUSING: demo accounts only")
        mt5.shutdown()
        return 1

    twin = args.magic + 10000 if args.magic < 960000 else args.magic - 10000
    bars = closed_bars(args.symbol, args.tf, EA_BARS)
    mt5.shutdown()
    if len(bars) < 300:
        print("not enough bars (%d)" % len(bars))
        return 1

    sigs = engine_signals(bars, args.mode)
    jrn = journal_lines(args.magic, args.days)
    starts = [t for t, l in jrn if "started on" in l]
    ea_start = min(starts) if starts else datetime.min.replace(tzinfo=None)
    opens_j = [(t, l) for t, l in jrn if " OPEN " in l and "ok=true" in l]
    entries = deal_entries(args.magic)
    twin_entries = deal_entries(twin)
    iv = open_intervals(entries)

    report = ["AetherFlow drift audit: %s %s %s-mode, magic %d (twin %d)"
              % (args.symbol, args.tf, args.mode, args.magic, twin),
              "  window: %d closed bars, %s .. %s UTC (EA window since %s)"
              % (len(bars),
                 bar_close_utc(bars[0]["time"], args.tf).strftime("%m-%d %H:%M"),
                 bar_close_utc(bars[-1]["time"], args.tf).strftime("%m-%d %H:%M"),
                 ea_start.strftime("%m-%d %H:%M"))]

    def filled_at(t_close):
        """(fill_dt, source) of a fill within tolerance, else None."""
        best = None
        for t, l in opens_j:
            if 0 <= (t - t_close).total_seconds() <= FILL_TOLERANCE_S:
                best = (t, "journal") if best is None or t < best[0] else best
        for r in entries:
            if 0 <= (r["_t"] - t_close).total_seconds() <= FILL_TOLERANCE_S:
                best = (r["_t"], "deals.csv") if best is None or r["_t"] < best[0] else best
        return best

    def open_side(t):
        for t_in, t_out, side in iv:
            if t_in <= t and (t_out is None or t < t_out):
                return side
        return None

    n_fill = n_skip = n_miss = n_pre = 0
    misses, extras = [], []
    matched_fill_times = set()
    for s in sigs:
        t_close = bar_close_utc(s["t_open"], args.tf)
        if t_close < ea_start:
            n_pre += 1
            continue
        f = filled_at(t_close)
        if f:
            n_fill += 1
            matched_fill_times.add(f[0])
            tw = any(abs((r["_t"] - f[0]).total_seconds()) <= FILL_TOLERANCE_S
                     for r in twin_entries)
            report.append("  %s %s @ %s [%s] -> FILLED %s (%s, twin %s)"
                          % (t_close.strftime("%m-%d %H:%M"), s["side"], s["close"],
                             s["members"], f[0].strftime("%H:%M:%SZ"), f[1],
                             "ok" if tw else "MISSING"))
        elif s["side"].lower() == (open_side(t_close) or ""):
            n_skip += 1
            report.append("  %s %s @ %s [%s] -> skipped-by-design (already %s)"
                          % (t_close.strftime("%m-%d %H:%M"), s["side"], s["close"],
                             s["members"], s["side"].lower()))
        else:
            n_miss += 1
            misses.append(s)
            report.append("  %s %s @ %s [%s] -> *** MISSED by EA ***"
                          % (t_close.strftime("%m-%d %H:%M"), s["side"], s["close"],
                             s["members"]))
    for t, l in opens_j:                       # EA fills with no engine signal
        if t < ea_start or any(abs((t - m).total_seconds()) <= FILL_TOLERANCE_S
                               for m in matched_fill_times):
            continue
        if any(abs((r["_t"] - t).total_seconds()) <= FILL_TOLERANCE_S
               for r in entries):
            mm = re.search(r"OPEN (BUY|SELL)", l)
            extras.append("  %s -> EA OPEN without engine signal: %s"
                          % (t.strftime("%m-%d %H:%M:%SZ"), mm.group(1) if mm else l))
    report.append("verdict: %d signals since EA start (%d before window) -> "
                  "%d filled, %d skipped-by-design, %d MISSED; %d extra EA fills"
                  % (n_fill + n_skip + n_miss, n_pre, n_fill, n_skip, n_miss,
                     len(extras)))
    report.extend(extras)

    # optional TradingView Pine cross-check
    if args.pine:
        pine = []
        try:
            for ln in open(args.pine, errors="replace"):
                m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})"
                              r"(?::\d{2})?\s*(buy|sell|long|short)?", ln, re.I)
                if m:
                    t = datetime.strptime(m.group(1) + " " + m.group(2),
                                          "%Y-%m-%d %H:%M")
                    side = (m.group(3) or "").lower()
                    pine.append((t, "BUY" if side in ("buy", "long") else
                                 "SELL" if side in ("sell", "short") else None))
        except OSError as e:
            report.append("pine file unreadable: %r" % e)
        if pine:
            eng_times = {(s["side"], bar_close_utc(s["t_open"], args.tf)
                          .replace(second=0)): s for s in sigs}
            only_p, only_e, both = [], [], 0
            for t, side in pine:
                hit = any(e_side == (side or e_side)
                          and abs((t - e_t).total_seconds()) <= TF_SEC[args.tf]
                          for (e_side, e_t) in eng_times)
                if hit:
                    both += 1
                else:
                    only_p.append((t, side))
            for (e_side, e_t), s in eng_times.items():
                if not any(abs((t - e_t).total_seconds()) <= TF_SEC[args.tf]
                           for t, _ in pine):
                    only_e.append((e_t, e_side, s["members"]))
            report.append("pine cross-check: %d alerts -> %d matched, "
                          "%d pine-only, %d engine-only"
                          % (len(pine), both, len(only_p), len(only_e)))
            for t, side in only_p[:8]:
                report.append("    pine-only: %s %s" % (t, side or "?"))
            for t, side, mem in only_e[:8]:
                report.append("    engine-only: %s %s [%s]" % (t, side, mem))
    else:
        report.append("pine cross-check: not provided (--pine alerts.txt)")

    text = "\n".join(report)
    print(text)
    if args.tg:
        send_telegram(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
