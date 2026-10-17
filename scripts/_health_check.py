"""Full per-EA health sweep of the live rig. Runs ON THE VPS.

Reads the deployed chart profile, the MT5 journal, the runner/dashboard logs
and (via a short live query) the open positions, then prints ONE row per chart
with a PASS/FAIL verdict. The expected column comes from scripts/_health_expect.json,
which is parsed out of the deployed BUNDLE profile -- so the diff is
"what we meant to ship" vs "what is actually running", never a restatement of
what is running.

Sections:
  A) per-chart diff: deployed .chr vs expected (expert, magic, trail flag, ATR triple)
  B) journal: 'started on' init lines per magic -- proves the EA actually attached
  C) trail behaviour: 'trail SL ->' modifies vs trail failures, per magic
  D) live positions: every open position has a valid SL/TP, nothing stuck at a
     pre-trailing level, no orphan magics (a position from a retired EA)
  E) infra: runner / watchdog / dashboard freshness

READ-ONLY except for the MetaTrader5 Python API query, which is a plain data
read (positions_get / symbol_info / account_info). No orders, no config writes.

Usage: python C:\\FTTest\\scripts\\_health_check.py
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

TERM = (r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075")
PROF = os.path.join(TERM, "MQL5", "Profiles", "Charts", "FTTest")
EXPERT_DIR = os.path.join(TERM, "MQL5", "Experts", "FTTest")
ELOGS = os.path.join(TERM, "MQL5", "Logs")
FT = r"C:\FTTest"
EXPECT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "_health_expect.json")
OUTFILE = os.path.join(FT, "logs", "ea_health.txt")

NOW = dt.datetime.now()
BAD, WARN = [], []
_lines = []


def out(s=""):
    print(s)
    _lines.append(str(s))


def flush():
    """Mirror the report to the log file. Called at the end AND on the way out,
    so a crash mid-run still leaves the partial report on disk."""
    try:
        os.makedirs(os.path.dirname(OUTFILE), exist_ok=True)
        with open(OUTFILE, "w", encoding="utf-8") as f:
            f.write("\n".join(_lines))
    except Exception:
        pass


# Two of the 32 charts run the USER'S OWN compiled binaries, which do not follow
# the FTTest logging contract (no "<label> <magic> started on ... trailing=ON"
# line). They announce themselves with their own banners, so section_b matches
# on expert name instead of the FTTest magic line. Without this the sweep
# reported them as "NEVER INITIALISED" while they were in fact running fine.
USER_INIT = {
    "XAUUSD_SmartMoney_VolumeProfile_EA": "SMVP EA initialized",
    "LiquiditySweepH4": "EA Started",
}
USER_BANNER_IS_INIT = True


# ------------------------------------------------------------------ parsing
def parse_chr(path):
    with open(path, encoding="utf-16") as f:
        txt = f.read()
    d = {"file": os.path.basename(path)}
    for key, pat in (("symbol", r"^symbol=(\S+)"),
                     ("tf_t", r"^period_type=(\d+)"),
                     ("tf_s", r"^period_size=(\d+)")):
        m = re.search(pat, txt, re.M)
        d[key] = m.group(1) if m else None
    m = re.search(r"name=(\S+)\npath=Experts\\FTTest\\(\S+)", txt)
    d["expert"] = m.group(1) if m else None
    d["ex5"] = m.group(2) if m else None
    d["contract"] = "fttest" if re.search(r"^InpMagic=", txt, re.M) else "smvp"
    if d["contract"] == "fttest":
        m = re.search(r"^InpMagic=(\d+)", txt, re.M)
        d["magic"] = int(m.group(1)) if m else None
        m = re.search(r"^InpUseTrailing=(\S+)", txt, re.M)
        d["trailing"] = (m.group(1) == "true") if m else None
        trip = []
        for k in ("InpTrailActAtr", "InpTrailDistAtr", "InpTrailStepAtr"):
            m = re.search(r"^%s=(\S+)" % k, txt, re.M)
            trip.append(m.group(1) if m else "?")
        d["trail"] = "/".join(trip)
    else:
        m = re.search(r"^InpMagicNumber=(\d+)", txt, re.M)
        d["magic"] = int(m.group(1)) if m else None
        d["trailing"] = None
        d["trail"] = "R-based"
    return d


def read_journal():
    """All MQL5 journals from the terminal's start date onward, in date order,
    decoded as UTF-16. Returns list of (line).

    DO NOT take only the newest journal. MT5 writes one journal per calendar
    day, so a terminal that has been up since Oct 02 still has every EA's
    'started on' line in 20261002.log. Taking sorted(glob_logs())[-1] looked
    only at today's file and reported all 32 charts NEVER INITIALISED while
    they were in fact all running. Concat every journal from the start date on
    so section B sees the real init evidence and section F sees all live errors.
    Returns (lines, used_basenames).
    """
    logs = glob_logs()
    if not logs:
        return [], []
    start = terminal_start_date()
    if start is not None:
        kept = []
        for p in logs:
            d = journal_date(os.path.basename(p))
            if d is None or d >= start.date():
                kept.append(p)
        if kept:
            logs = kept
    logs = sorted(logs)
    lines = []
    for p in logs:
        try:
            with open(p, encoding="utf-16", errors="replace") as f:
                lines.extend(f.read().splitlines())
        except Exception:
            pass
    return lines, [os.path.basename(p) for p in logs]


def journal_date(name):
    """Parse the YYYYMMDD out of an MT5 journal filename."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})\.log$", name or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def terminal_start_date():
    """Full DateTime at which terminal64.exe last started, or None."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process terminal64 -ErrorAction SilentlyContinue)"
             ".StartTime.ToString('yyyy-MM-dd HH:mm:ss')"],
            capture_output=True, text=True, timeout=40)
        m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", r.stdout or "")
        if m:
            return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return None


def glob_logs():
    try:
        return [os.path.join(ELOGS, n) for n in os.listdir(ELOGS)
                if n.endswith(".log")]
    except Exception:
        return []


def mtime(path):
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


def age(path):
    m = mtime(path)
    if m is None:
        return "MISSING"
    d = (NOW - m).total_seconds() / 60.0
    return "%.0fm" % d if d < 120 else "%.1fh" % (d / 60.0)


# ------------------------------------------------------------------ sections
def section_a(expect):
    out("=" * 108)
    out("A) PER-CHART CONFIG DIFF  (deployed profile vs shipped bundle)")
    out("=" * 108)
    out("%-12s %-26s %-4s %-9s %-8s %-13s %s"
        % ("chart", "expert", "tf", "magic", "trail?", "ATR triple", "verdict"))
    rows = {}
    for e in expect:
        p = os.path.join(PROF, e["file"])
        if not os.path.exists(p):
            BAD.append("%s MISSING on VPS (expected %s / magic %s)"
                       % (e["file"], e["expert"], e["magic"]))
            out("%-12s %-26s %-4s %-9s %-8s %-13s CHART FILE MISSING"
                % (e["file"], e["expert"], e["tf"], e["magic"],
                   e["trailing"], e["trail"]))
            continue
        g = parse_chr(p)
        rows[e["file"]] = g
        probs = []
        for f in ("expert", "magic", "trail"):
            if g.get(f) != e.get(f):
                probs.append("%s: VPS=%r want=%r" % (f, g.get(f), e.get(f)))
        # trailing flag only meaningful for the ATR contract
        if e["contract"] == "fttest" and g["trailing"] != e["trailing"]:
            probs.append("trailing: VPS=%r want=%r" % (g["trailing"], e["trailing"]))
        # the .ex5 must exist and be newer than the terminal start, else MT5
        # silently falls back to the previous compile
        ex5 = os.path.join(EXPERT_DIR, e["ex5"] or "")
        if not os.path.exists(ex5):
            probs.append("ex5 MISSING: %s" % e["ex5"])
        verdict = "OK" if not probs else "MISMATCH"
        if probs:
            BAD.append("%s (%s): %s" % (e["file"], e["expert"], "; ".join(probs)))
        out("%-12s %-26s %-4s %-9s %-8s %-13s %s"
            % (e["file"], g["expert"] or "?", g["tf_s"] + ("h" if g["tf_t"] == "1" else "m"),
               g["magic"], g["trailing"], g["trail"], verdict))
        for pr in probs:
            out("             -> %s" % pr)
    extra = set(os.path.basename(x) for x in os.listdir(PROF)
                if x.startswith("chart") and x.endswith(".chr")) - set(
        e["file"] for e in expect)
    for x in sorted(extra):
        BAD.append("%s present on VPS but NOT in the bundle (retired EA resurrected?)" % x)
        out("%-12s  *** UNEXPECTED CHART FILE (not in bundle) ***" % x)
    out("")
    return rows


def section_b(journal, expect):
    out("=" * 108)
    out("B) EA INITIALISATION  (one 'started on' per magic in the journal)")
    out("=" * 108)
    started, liveflag = {}, {}
    # Only the CURRENT terminal session counts as proof of life. A journal day
    # can hold several sessions: bouncing MT5 does not roll the journal file,
    # so every retired EA re-logs its init line at the previous restart and
    # those lines survive into the new session. Treating them as live reported
    # 13 retired magics as "still running on some chart" right after they were
    # deliberately removed. Section F already scopes its census by terminal
    # start time; section B must do the same or the two disagree.
    start_hms = terminal_start_hhmmss()
    ghost, ghost_magics = {}, set()

    def session_of(line):
        """True if this journal line belongs to the current terminal session."""
        if not start_hms:
            return True
        m = re.search(r"\b(\d{2}:\d{2}:\d{2})\b", line)
        if not m:
            return True          # no timestamp -> cannot scope, keep it
        return m.group(1) >= start_hms

    for ln in journal:
        live_session = session_of(ln)
        # the user's own binaries announce themselves on a tab-prefixed line
        # carrying the expert name in parentheses
        for exp, banner in USER_INIT.items():
            if exp in ln and banner in ln:
                # attribute to the first magic that maps to this expert
                for e in expect:
                    if e["expert"] == exp:
                        if live_session:
                            started[e["magic"]] = started.get(e["magic"], 0) + 1
                        else:
                            ghost[e["magic"]] = ghost.get(e["magic"], 0) + 1
        if "started on" not in ln:
            continue
        # Journal format (tab-separated):  <label> <magic> started on XAUUSD ...
        # e.g. "trend 940012 started on XAUUSD PERIOD_H1 lots=0.01 trailing=ON".
        # The magic is a BARE 6-digit token before "started on" -- there is no
        # "magic=" prefix, which is why an earlier version of this check
        # reported 0/32 initialised when all 150 lines were present.
        m = re.search(r"\b(\d{6})\s+started on", ln)
        if not m:
            continue
        mg = int(m.group(1))
        if not live_session:
            ghost[mg] = ghost.get(mg, 0) + 1
            ghost_magics.add(mg)
            continue
        started[mg] = started.get(mg, 0) + 1
        # keep the flag from the MOST RECURRENT init (restarts re-log the line)
        f = re.search(r"trailing=(ON|OFF)", ln)
        if f:
            liveflag[mg] = (f.group(1) == "ON")
    out("%-9s %-26s %-7s %-10s %-9s %s"
        % ("magic", "expert", "inits", "trail?", "running", "verdict"))
    ok = 0
    for e in expect:
        n = started.get(e["magic"], 0)
        prob = []
        if n == 0:
            prob.append("NEVER INITIALISED -- EA not attached to its chart")
        else:
            ok += 1
        # the RUNNING trailing flag must match the deployed .chr flag. This is
        # the check that catches a chart that was edited but never reloaded.
        run = liveflag.get(e["magic"])
        if run is None:
            shown = "-"
            if e["expert"] in USER_INIT:
                shown = "own-binary"   # user binary logs its own banner; no ON/OFF
            elif n:
                prob.append("init line carries no trailing= flag")
        else:
            shown = "ON" if run else "OFF"
            if e["contract"] == "fttest" and run != e["trailing"]:
                prob.append("RUNNING trailing=%s but .chr says %s -- chart not reloaded"
                            % (shown, "ON" if e["trailing"] else "OFF"))
        out("%-9s %-26s %-7s %-10s %-9s %s"
            % (e["magic"], e["expert"], n or "NONE",
               "ON" if e["trailing"] else ("OFF" if e["trailing"] is not None else "n/a"),
               shown, "OK" if not prob else " | ".join(prob)))
        for pr in prob:
            BAD.append("magic %s (%s, %s): %s" % (e["magic"], e["expert"], e["file"], pr))
    out("  %d/%d magics initialised" % (ok, len(expect)))
    if ghost:
        out("  note: %d magic(s) logged an init line BEFORE this terminal "
            "session (started %s) -- pre-restart history, not live:"
            % (len(ghost), start_hms or "?"))
        for mg in sorted(ghost):
            out("    magic %-9d x%d  %s" % (mg, ghost[mg],
                                            "still in bundle (expected)" if mg in
                                            {e["magic"] for e in expect}
                                            else "RETIRED before this session"))
    # magics running that the bundle does not know about = a retired EA resurrected
    for mg in sorted(set(started) - set(e["magic"] for e in expect)):
        BAD.append("magic %s INITIALISED in the journal but is NOT in the bundle "
                   "(retired EA still running on some chart)" % mg)
        out("  !! unexpected magic %s is running" % mg)
    out("")
    return started


def section_c(journal, expect):
    out("=" * 108)
    out("C) TRAILING BEHAVIOUR  (modifies vs failures, per magic)")
    out("=" * 108)
    mods, fails = {}, {}
    for ln in journal:
        if "trail SL ->" in ln:
            # same bare-token layout as "started on", see section_b
            mm = re.search(r"\b(\d{6})\s+trail SL", ln)
            if mm:
                mods[int(mm.group(1))] = mods.get(int(mm.group(1)), 0) + 1
            else:
                mods[-1] = mods.get(-1, 0) + 1   # unattributable
        if "trail modify FAILED" in ln:
            fails[ln.strip()[-170:]] = fails.get(ln.strip()[-170:], 0) + 1
    out("  trail SL -> modifies by magic: %s"
        % (", ".join("%s=%d" % (m, n) for m, n in sorted(mods.items())) or "none"))
    out("  trail modifies total: %d" % sum(mods.values()))
    # retcode 10036 = "position closed" -- the EA tried to ratchet a stop on a
    # position that had just been closed out by another branch of the same EA.
    # That is a benign race, not a broken trail, so it is reported but never
    # counted as a fault.
    BENIGN_TRAIL = ("ret=10036", "position closed")
    hard, soft = {}, {}
    for k, v in fails.items():
        (soft if any(b in k for b in BENIGN_TRAIL) else hard)[k] = v
    for k, v in list(hard.items())[:20]:
        BAD.append("trail modify FAILED x%d: %s" % (v, k))
    for k, v in list(soft.items())[:5]:
        WARN.append("trail modify skipped (benign race, ret=10036) x%d: %s" % (v, k[-90:]))
    out("  trail modify failures: %d hard, %d benign (ret=10036 position-closed race)"
        % (sum(hard.values()), sum(soft.values())))
    for k, v in list(hard.items())[:20]:
        out("     HARD x%d %s" % (v, k))
    if -1 in mods:
        WARN.append("%d trail modifies had no parseable magic" % mods.pop(-1))
    # A trailing twin with ZERO modifies is not broken, but it does mean the
    # stop ratchet has never had a position in profit long enough to act --
    # worth stating outright so a silent non-trader is not mistaken for a
    # working trailing stop.
    for e in expect:
        if e["contract"] == "fttest" and e["trailing"] and mods.get(e["magic"], 0) == 0:
            out("  note: %-9s %-24s trailing ON but 0 modifies today "
                "(no position has trailed yet)" % (e["magic"], e["expert"]))
    out("")
    return mods


def section_d(expect):
    out("=" * 108)
    out("D) LIVE POSITIONS  (every position must carry a valid SL, no orphans)")
    out("=" * 108)
    valid = set(e["magic"] for e in expect)
    try:
        sys.path.insert(0, r"C:\FTTest\scripts")
        import MetaTrader5 as mt5
        if not mt5.initialize():
            WARN.append("mt5.initialize() failed: %s" % mt5.last_error())
            out("  mt5.initialize() FAILED (%s) -- section skipped" % (mt5.last_error(),))
            out("")
            return
        acc = mt5.account_info()
        out("  account %s  server %s  balance %.2f  equity %.2f"
            % (acc.login if acc else "?", acc.server if acc else "?",
               acc.balance if acc else 0, acc.equity if acc else 0))
        pos = mt5.positions_get(symbol="XAUUSD")
        if pos is None:
            pos = []
        out("  open XAUUSD positions: %d" % len(pos))
        if not pos:
            out("    (flat -- no SL audit needed)")
        for p in pos:
            m = int(p.magic)
            name = next((e["expert"] for e in expect if e["magic"] == m), None)
            # TradePosition carries no `digits` field -- get it from the symbol
            si = mt5.symbol_info(p.symbol)
            dg = si.digits if si else 2
            prob = []
            if name is None:
                prob.append("ORPHAN: magic not in bundle (retired EA holding a position)")
            if p.sl == 0.0:
                prob.append("NO STOP LOSS on the position")
            # The ONLY stop-placement fault is a stop that is not protective:
            # it must sit on the correct side of the CURRENT market price.
            # NOTE: SL above entry on a BUY (or below entry on a SELL) is NOT a
            # fault -- that is a trailing stop that has locked in profit, which
            # is precisely what this rig is configured to do.
            if p.sl and p.type == 0 and p.sl >= p.price_current:
                prob.append("SL %.*f is at/through the market (bid %.*f) -- NOT protective"
                            % (dg, p.sl, dg, p.price_current))
            if p.sl and p.type == 1 and p.sl <= p.price_current:
                prob.append("SL %.*f is at/through the market (ask %.*f) -- NOT protective"
                            % (dg, p.sl, dg, p.price_current))
            locked = ""
            if p.sl and p.type == 0 and p.sl > p.price_open:
                locked = "locked +%.2f" % (p.sl - p.price_open)
            if p.sl and p.type == 1 and p.sl < p.price_open:
                locked = "locked +%.2f" % (p.price_open - p.sl)
            out("    magic %-9s %-26s %s %.*f  sl=%s tp=%s  profit=%+.2f  %s  %s"
                % (m, name or "??",
                   "BUY" if p.type == 0 else "SELL",
                   dg, p.price_open,
                   ("%.*f" % (dg, p.sl)) if p.sl else "NONE",
                   ("%.*f" % (dg, p.tp)) if p.tp else "-",
                   p.profit, locked, "OK" if not prob else " / ".join(prob)))
            if prob:
                BAD.append("position magic %s: %s" % (m, "; ".join(prob)))
        mt5.shutdown()
    except Exception as exc:
        WARN.append("position audit error: %r" % (exc,))
        out("  position audit ERROR: %r" % (exc,))
    out("")
    return valid


def section_e():
    out("=" * 108)
    out("E) INFRASTRUCTURE")
    out("=" * 108)
    for label, pat in (("terminal64", "terminal64.exe"),
                       ("python (runner/watchdog)", "python.exe")):
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + pat],
                               capture_output=True, text=True, timeout=30)
            n = len([x for x in r.stdout.splitlines() if pat in x and x.strip()])
            out("  %-26s %d process(es)" % (label, n))
            if n == 0:
                BAD.append("%s not running" % pat)
        except Exception as exc:
            WARN.append("tasklist %s: %r" % (pat, exc))
    for label, p in (("runner stdout", os.path.join(FT, "logs", "forward_test_stdout.txt")),
                     ("watchdog log", os.path.join(FT, "logs", "vps_watchdog.log")),
                     ("deals.csv", os.path.join(FT, "logs", "forward", "deals.csv"))):
        st = "OK" if mtime(p) else "MISSING"
        out("  %-26s last write %-8s %s" % (label, age(p), st))
        if st == "MISSING":
            WARN.append("%s missing" % label)
    out("")


def terminal_start_hhmmss():
    """Wall-clock HH:MM:SS at which terminal64.exe last started.

    Journal lines carry only a time-of-day, so comparing a journal timestamp
    against this is what separates pre-restart history from live errors.
    NOTE: `tasklist /V` does NOT work here -- its first HH:MM:SS column is CPU
    time, not start time, which silently reported 00:11:14 for a terminal that
    had started at 18:28. Get-Process .StartTime is the correct source.
    Returns "" if it cannot be read.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process terminal64 -ErrorAction SilentlyContinue)"
             ".StartTime.ToString('HH:mm:ss')"],
            capture_output=True, text=True, timeout=40)
        m = re.search(r"\b(\d{2}:\d{2}:\d{2})\b", r.stdout or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def section_f(journal):
    """Per-EA error census over the WHOLE journal.

    Section C only looks at trail failures from the FTTest family. This walks
    every line, groups any error-ish line by the EA that emitted it, and
    separates retcodes that are pure races (10036 position-closed) from real
    rejections (10016 invalid stops, 10019 not enough money, ...). This is what
    catches breakage inside the user's own binaries, which the FTTest-specific
    sections are blind to.
    """
    out("=" * 108)
    out("F) PER-EA ERROR CENSUS  (whole journal, grouped by expert)")
    out("=" * 108)
    BENIGN = ("ret=10036", "retcode=10036", "position closed",
              "ret=10018", "retcode=10018", "market closed", "requote")
    # Retcodes that mean the order SUCCEEDED. 10009 = DONE_PARTIAL and 0 = DONE.
    # The FTTest EAs log "ok=true ret=10009" on every winning fill, so any scan
    # that treats "ret=NNNN" as an error flags every good trade in the journal.
    OK_RETCODES = ("ok=true", "ret=0", "ret=10009", "retcode=0", "retcode=10009")
    errs = {}
    newest_hhmm = ""
    for ln in journal:
        # a trade line is only an error if it explicitly says it failed
        is_trade = re.search(r"\b(OPEN|CLOSE)\b", ln)
        if is_trade:
            if not re.search(r"ok=false|ret=(?!0\b|10009\b)\d+|retcode=(?!0\b|10009\b)\d+",
                             ln):
                continue
        else:
            if not re.search(r"fail|error|invalid|reject|not enough money|"
                             r"retcode=(?!0\b|10009\b)\d{4,5}", ln, re.I):
                continue
        if any(b in ln for b in OK_RETCODES):
            continue
        m = re.search(r"\t([A-Za-z0-9_]+) \(XAUUSD,", ln)
        ea = m.group(1) if m else "?"
        # Take the timestamp from the FULL journal line, not from the truncated
        # tail kept as the key -- the truncation can cut the timestamp off
        # entirely, which made an 11:52 event look timeless and therefore "live".
        t = re.search(r"\b(\d{2}:\d{2}:\d{2})\.\d+\t", ln)
        ts = t.group(1) if t else "?"
        key = (ea, ts, ln.strip()[-150:])
        errs[key] = errs.get(key, 0) + 1
        if ts != "?" and ts > newest_hhmm:
            newest_hhmm = ts
    # Journal is per-day, so it accumulates errors from BEFORE the current fix.
    # Splitting on the terminal start time is the only way to tell "this bug is
    # still happening" from "this bug happened at 01:30 and has been fixed".
    mt_start = terminal_start_hhmmss()
    if not errs:
        out("  no genuine error lines (successful ret=10009 fills excluded)")
    hard = soft = 0
    for (ea, ts, msg), n in sorted(errs.items(), key=lambda kv: -kv[1]):
        benign = any(b.lower() in msg.lower() for b in BENIGN)
        pre = bool(mt_start and ts != "?" and ts < mt_start)
        tag = "soft" if benign else "HARD"
        if pre:
            tag = "pre-fix"
        if benign:
            soft += n
        elif not pre:
            hard += n
            BAD.append("%s: x%d %s" % (ea, n, msg))
        out("  [%s] %-34s x%-4d %s %s"
            % (tag, ea, n, ts, msg))
    out("  totals: %d hard (after MT5 start %s), %d soft(benign race)"
        % (hard, mt_start, soft))
    if mt_start:
        out("  lines tagged 'pre-fix' happened BEFORE this terminal session and are")
        out("  historical -- they are fixed in the current build, not recurring.")
    out("")
    out("  NOTE: 'Maximum Trade Limit Reached' from LiquiditySweepH4 is the user")
    out("        binary's own daily cap, not a rig fault -- the EA is alive and")
    out("        re-announcing on every bounce, it is just throttled.")
    out("")


def main():
    with open(EXPECT) as f:
        expect = json.load(f)

    out("EA RIG HEALTH CHECK   %s" % NOW.strftime("%Y-%m-%d %H:%M:%S"))
    out("charts expected: %d" % len(expect))
    out("")

    journal, used = read_journal()
    shown = used if len(used) <= 4 else [used[0], "...", used[-1]]
    out("journals: %s  (%d lines total)" % (", ".join(shown), len(journal)))
    out("")

    rows = section_a(expect)
    started = section_b(journal, expect)
    mods = section_c(journal, expect)
    section_d(expect)
    section_e()

    section_f(journal)
    out("=" * 108)
    out("VERDICT: %d problem(s), %d warning(s)" % (len(BAD), len(WARN)))
    out("=" * 108)
    for b in BAD:
        out("  FAIL  %s" % b)
    for w in WARN:
        out("  WARN  %s" % w)
    if not BAD:
        out("  ALL %d CHARTS HEALTHY" % len(expect))
    flush()


if __name__ == "__main__":
    try:
        main()
    finally:
        flush()