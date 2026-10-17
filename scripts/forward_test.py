"""Forward-test LOGGER: harvests EA deals into deals.csv and snapshots
account equity into equity.csv. Runs on the DEMO account in real time.

EA-ONLY RIG: every strategy is implemented as an MT5 EA (FTTest_<strategy>.mq5,
FTTestMultiEA, AetherFlowEA, SMVP). This process sends NO orders, trails
NOTHING, seeds NOTHING -- all trading and all trailing stops live in the EAs.
The old python trading path (send_market/_run_dual/trail_positions/seed_twins/
act_on_signal) was removed; the strategy functions below remain only because
the backtest harnesses (backtest_all_7.py, backtest_trailing_check.py,
weekly_verdict_refresh.py) import them.

Safety rails:
  1. NEVER auto-launches MT5: checks tasklist first, asks user to open MT5.
  2. DEMO accounts ONLY -- hard-refuses real/live accounts.
  3. Credentials only from .env (git-ignored).

Usage:
  python scripts/forward_test.py --check    # preflight only
  python scripts/forward_test.py            # run the logger loop

Logs: logs/forward/deals.csv (every deal with real price/commission/slippage)
      logs/forward/equity.csv (balance/equity snapshots)
Charts: python scripts/forward_charts.py
"""

import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAGICS = {
    910001: "breakout", 920001: "breakout-T",
    910002: "meanrev",  920002: "meanrev-T",
    910003: "macross",  920003: "macross-T",
    910004: "straddle", 920004: "straddle-T",
    # FTTestEA instances (magic range 930/940) are LOGGED here so the
    # dashboard charts EA results too -- this runner never trades them.
    930001: "breakout-EA", 940001: "breakout-EA-T",
    930002: "meanrev-EA",  940002: "meanrev-EA-T",
    930003: "macross-EA",  940003: "macross-EA-T",
    930004: "straddle-EA", 940004: "straddle-EA-T",
    930005: "smc-EA",      940005: "smc-EA-T",
    930006: "london-EA",   940006: "london-EA-T",
    930007: "squeeze-EA",  940007: "squeeze-EA-T",
    # NEW strategies last so equity.csv column positions of the old series
    # stay stable (columns are written in dict order):
    930008: "profile-EA",  940008: "profile-EA-T",
    930009: "fixfade-EA", 940009: "fixfade-EA-T",   # was orderflow (0 trades) -- repurposed 10/01
    910005: "smc",     920005: "smc-T",
    910006: "london",  920006: "london-T",
    910007: "squeeze", 920007: "squeeze-T",
    # user's own SMVP scalper EA (XAUUSD chart16, fixed 0.01 lot since
    # 2026-10-01, was 0.25% risk) -- logged only,
    # this runner never trades it
    26092501: "smvp",
    # AetherFlow EA (MQL5 port of the Pine "Aether Flow" system) -- logged
    # only, this runner never trades it. M15 confluence twins (charts 17/18)
    # and M30 UT-only twins (charts 19/20; 30d M30 verdict: trail +$73 PF 1.12)
    950001: "aetherflow",
    960001: "aetherflow-T",
    950002: "aetherflow-M30",
    960002: "aetherflow-M30-T",
    # chart25-28 (added 2026-09-28, backtested in backtest_new_candidates.py):
    # TrendPullback H1-trend/M15-pullback + Donchian-20 on H1, fixed/trail
    930010: "trendpullback-EA", 940010: "trendpullback-EA-T",
    930011: "donchian-EA",      940011: "donchian-EA-T",
    # chart29-33 (added 2026-09-29): trend (H1 EMA trend+momentum, charts
    # 29-30) + supres (S/R window-rejection bounce, charts 31-32), fixed/trail
    # twins; aetherflow-H4 UT-only twins on the H4 host chart (chart 33)
    930012: "trend-EA",      940012: "trend-EA-T",
    930013: "vwaprev-EA",    940013: "vwaprev-EA-T",   # was supres (WF bleed) -- repurposed 10/01
    950003: "aetherflow-H4", 960003: "aetherflow-H4-T",
    # chart35-36 (added 2026-09-30): supertrend (Pine ta.supertrend flip,
    # faithful port after the broken-helper fix) on the H1 host chart
    930014: "supertrend-EA", 940014: "supertrend-EA-T",
    # chart37-38 (added 2026-09-30): liquiditysweep A/B on the H4 host chart
    # -- native port (930015) vs the user's compiled LiquiditySweepH4 binary
    # (930016, FTTest-format inputs written into its .chr; its real internal
    # inputs are unknown until its first trade/reload reveals them)
    930015: "liquiditysweep-EA",
    930016: "liquiditysweep-BIN",
    # chart39 (added 2026-10-02): dayopen -- weekday server-day-open long
    # (single fixed instance; backtest 180d +$796 PF 1.40, weekday-only
    # +$788 avg +$5.32 n=148, matched-time controls lose -> not beta)
    930017: "dayopen-EA",
    # swing (added 2026-10-05): H1 structure bias + M15/M30 EMA21 pullback
    # rejection. Walk-forward 52/52 profitable on M15 and M30; H1 decays so it
    # was never deployed. Magics append-only.
    930018: "swing-EA", 940018: "swing-EA-T",
    930019: "swing-m30-EA", 940019: "swing-m30-EA-T",
    # sweepabs (added 2026-10-06): M15 sweep + volume absorption, market
    # entry. Backtest 200d cost-aware fixed -$987 / trail +$1087 PF 1.30.
    # Magics append-only.
    930020: "sweepabs-EA", 940020: "sweepabs-EA-T",
    # GridRecoveryEA v2 (single-side + AUTO EMA trend + catastrophic SL,
    # added 2026-10-14, chart XAUUSD; solo magic, no twin)
    930021: "grid-EA",
    # SlipstreamCloneEA (faithful port of live 33705313 magic 300003:
    # hedged, step 350pts, lots 0.01,0.01,0.02.., TP 180, max 12, no SL)
    # added 2026-10-14, 2nd XAUUSD chart; solo magic, no twin
    930022: "gridclone-EA",
    # GridBestRREA (recommended hybrid: AUTO single-side, step 350, lots
    # 0.01,0.01,0.02.., TP 180 server-side, catastrophic SL, max 6)
    # added 2026-10-14, 3rd XAUUSD chart; solo magic, no twin
    930023: "gridbestrr-EA",
}
# Multi-symbol magics (appended last so equity.csv columns stay positional-stable):
# XAUUSD keeps 9100xx/9200xx; EURUSD 9110xx/9210xx, GBPUSD 9120xx/9220xx,
# USDJPY 9130xx/9230xx, AUDUSD 9140xx/9240xx (same 7 strategies each).
# XAU-ONLY RIG (2026-09-28): FX retired from trading AND testing. This list
# drives the runner preflight/logging scope and every harness that imports it.
SYMBOLS = ["XAUUSD"]
SYMBOL_CODES = {"EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY", "AUDUSD": "AUD"}
STRAT_NAMES = ("breakout", "meanrev", "macross", "straddle", "smc", "london", "squeeze")
SYMBOL_BASE = {"XAUUSD": 910000, "EURUSD": 911000, "GBPUSD": 912000,
               "USDJPY": 913000, "AUDUSD": 914000}
for _sym in SYMBOL_CODES:
    for _i, _sname in enumerate(STRAT_NAMES, start=1):
        MAGICS[SYMBOL_BASE[_sym] + _i] = "%s-%s" % (_sname, SYMBOL_CODES[_sym])
        MAGICS[SYMBOL_BASE[_sym] + 10000 + _i] = "%s-%s-T" % (_sname, SYMBOL_CODES[_sym])
        # FTTestMultiEA streams (base = python base +20000, trailing +10000 more):
        # logged so deals.csv/dashboard capture them; this runner never trades them
        MAGICS[SYMBOL_BASE[_sym] + 20000 + _i] = "%s-%s-EA" % (_sname, SYMBOL_CODES[_sym])
        MAGICS[SYMBOL_BASE[_sym] + 30000 + _i] = "%s-%s-EA-T" % (_sname, SYMBOL_CODES[_sym])
    # FTTestMultiEA v2 also runs profile + orderflow on the FX pairs
    # (strategy indices 8/9, MultiEA base +20000 / trailing +30000). The
    # python twins (9110xx/9210xx idx 8/9) intentionally stay unallocated.
    for _j, _sname2 in enumerate(("profile", "orderflow"),
                                 start=len(STRAT_NAMES) + 1):
        MAGICS[SYMBOL_BASE[_sym] + 20000 + _j] = "%s-%s-EA" % (_sname2, SYMBOL_CODES[_sym])
        MAGICS[SYMBOL_BASE[_sym] + 30000 + _j] = "%s-%s-EA-T" % (_sname2, SYMBOL_CODES[_sym])
# The runner no longer trades or trails anything (EA-only rig); the twin
# magics stay in MAGICS purely so deals.csv keeps logging them.
# London-open breakout session bounds in SERVER hours (Fusion server ~= UTC+3,
# so London open 08:00 UTC ~= 11:00 server). Asian range = same-day bars before
# LONDON_START_HOUR.
LONDON_START_HOUR = 11
LONDON_END_HOUR = 17
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "forward")
DEALS_CSV = os.path.join(LOG_DIR, "deals.csv")
EQUITY_CSV = os.path.join(LOG_DIR, "equity.csv")
LOOP_SEC = 30
SNAPSHOT_EVERY = 10  # loops between equity snapshots (~5 min)

DEAL_FIELDS = ["time_utc", "ticket", "magic", "strategy", "position_id", "symbol",
               "type", "entry", "volume", "price", "commission", "swap", "profit", "comment"]


# ---------------------------------------------------------------- safety rails

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[%s] %s" % (ts, msg), flush=True)


def load_env():
    env = {}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, ".env")
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
    return "terminal64.exe" in out or "terminal.exe" in out


# ---------------------------------------------------------------- math helpers

def atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def ema(closes, period):
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(closes[:period]) / period
    for c in closes[period:]:
        e = c * k + e * (1 - k)
    return e


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


# --------------------------------------------------------------- MT5 plumbing

import MetaTrader5 as mt5  # noqa: E402

TF = {"M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
      "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}


def closed_bars(symbol, tf, n=300):
    rates = mt5.copy_rates_from_pos(symbol, TF[tf], 1, n)  # shift 1 = last *closed* bar
    if rates is None or len(rates) == 0:
        return []
    return [{"time": int(r["time"]), "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"]} for r in rates]


def resolve_symbol(base):
    info = mt5.symbol_info(base)
    if info is not None:
        mt5.symbol_select(base, True)
        return base
    for s in (mt5.symbols_get("*" + base[:3] + "*") or []):
        if base in s.name.upper():
            mt5.symbol_select(s.name, True)
            return s.name
    raise RuntimeError("symbol %s not found" % base)


# ------------------------------------------------------------------ strategies
# Each returns: ("entry", side, sl, tp) | ("reverse", side, sl, tp) | ("close",) | None

def strat_breakout(bars):
    if len(bars) < 25:
        return None
    a = atr(bars)
    if not a:
        return None
    hi = max(b["high"] for b in bars[-21:-1])
    lo = min(b["low"] for b in bars[-21:-1])
    last = bars[-1]
    if last["close"] > hi:
        return ("entry", "buy", last["close"] - 2 * a, last["close"] + 3 * a)
    if last["close"] < lo:
        return ("entry", "sell", last["close"] + 2 * a, last["close"] - 3 * a)
    return None


def strat_meanrev(bars):
    if len(bars) < 20:
        return None
    a = atr(bars)
    if not a:
        return None
    r = rsi([b["close"] for b in bars])
    if r is None:
        return None
    px = bars[-1]["close"]
    if r < 25:
        return ("entry", "buy", px - 1.5 * a, px + 1.0 * a)
    if r > 75:
        return ("entry", "sell", px + 1.5 * a, px - 1.0 * a)
    return None


def strat_macross(bars):
    if len(bars) < 30:
        return None
    a = atr(bars)
    if not a:
        return None
    closes = [b["close"] for b in bars]
    f, s = ema(closes[-60:], 9), ema(closes[-60:], 21)
    fp, sp = ema(closes[-61:-1], 9), ema(closes[-61:-1], 21)
    if None in (f, s, fp, sp):
        return None
    px = closes[-1]
    if fp <= sp and f > s:
        return ("entry", "buy", px - 2 * a, px + 3 * a)
    if fp >= sp and f < s:
        return ("entry", "sell", px + 2 * a, px - 3 * a)
    return None


def strat_straddle(bars):
    """Levels only -- the runner places/cancels the stop orders."""
    if len(bars) < 6:
        return None
    a = atr(bars)
    if not a:
        return None
    hi = max(b["high"] for b in bars[-4:])
    lo = min(b["low"] for b in bars[-4:])
    buf = 0.25 * a
    return {"buy_stop": hi + buf, "sell_stop": lo - buf, "risk": a}


def strat_smc(bars):
    """Liquidity sweep + rejection candle (mirrors the EA's smc strategy):
    wick beyond the prior 20-bar extreme closing back inside, small body,
    SL beyond the sweep wick, TP = 3x risk (~1:3 R:R)."""
    if len(bars) < 25:
        return None
    a = atr(bars)
    if not a:
        return None
    hi = max(b["high"] for b in bars[-22:-1])
    lo = min(b["low"] for b in bars[-22:-1])
    b = bars[-1]
    rng = b["high"] - b["low"]
    if rng <= 0:
        return None
    body = abs(b["close"] - b["open"])
    body_ratio = body / rng
    lower_wick = min(b["open"], b["close"]) - b["low"]
    upper_wick = b["high"] - max(b["open"], b["close"])
    small_body = (body_ratio <= 0.30) or (body_ratio <= 0.45 and
                  (lower_wick > 2 * body or upper_wick > 2 * body))
    # bullish sweep: dip below prior low, close back above + hammer/doji
    if b["low"] < lo and b["close"] > lo and small_body and lower_wick > 0.5 * rng:
        entry = b["close"]
        sl = b["low"] - 0.1 * a
        risk = entry - sl
        if risk > 0:
            return ("entry", "buy", sl, entry + 3 * risk)
        return None
    # bearish sweep: spike above prior high, close back below + rejection
    if b["high"] > hi and b["close"] < hi and small_body and upper_wick > 0.5 * rng:
        entry = b["close"]
        sl = b["high"] + 0.1 * a
        risk = sl - entry
        if risk > 0:
            return ("entry", "sell", sl, entry - 3 * risk)
    return None


def strat_london(bars):
    """London-open breakout of the Asian range. Levels only -- the runner
    places/cancels the stop orders once per day."""
    if len(bars) < 30:
        return None
    a = atr(bars)
    if not a:
        return None
    last = bars[-1]
    day = last["time"] // 86400
    hour = (last["time"] % 86400) // 3600
    if not (LONDON_START_HOUR <= hour < LONDON_END_HOUR):
        return None
    asian = [b for b in bars
             if b["time"] // 86400 == day
             and (b["time"] % 86400) // 3600 < LONDON_START_HOUR]
    if len(asian) < 4:
        return None
    hi = max(b["high"] for b in asian)
    lo = min(b["low"] for b in asian)
    if hi <= lo:
        return None
    buf = 0.25 * a
    return {"buy_stop": hi + buf, "sell_stop": lo - buf, "risk": a}


def _bb(closes, end):
    """(mid, std) of closes[end-19..end], population stdev. None if too short."""
    if end < 19:
        return None, None
    seg = closes[end - 19:end + 1]
    mid = sum(seg) / 20.0
    var = sum((c - mid) ** 2 for c in seg) / 20.0
    return mid, var ** 0.5


def strat_squeeze(bars):
    """Bollinger(20,2) compressed inside Keltner(20,1.5*ATR) on >=6 of the
    prior 10 bars -> enter on the expansion close beyond the Bollinger band.
    (Keltner width uses the latest ATR for all checked bars -- the EA mirrors
    this approximation exactly so results stay comparable.)"""
    if len(bars) < 30:
        return None
    a = atr(bars)
    if not a:
        return None
    closes = [b["close"] for b in bars]
    squeezed = 0
    for idx in range(len(bars) - 11, len(bars) - 1):
        mid, sd = _bb(closes, idx)
        if mid is None:
            continue
        e = ema(closes[:idx + 1], 20)
        if e is None:
            continue
        if mid + 2 * sd < e + 1.5 * a and mid - 2 * sd > e - 1.5 * a:
            squeezed += 1
    if squeezed < 6:
        return None
    mid, sd = _bb(closes, len(closes) - 1)
    if mid is None:
        return None
    px = closes[-1]
    if px > mid + 2 * sd:
        return ("entry", "buy", px - 2 * a, px + 3 * a)
    if px < mid - 2 * sd:
        return ("entry", "sell", px + 2 * a, px - 3 * a)
    return None


def strat_trendpullback(bars):
    """H1 trend + M15 pullback (EA: SigTrendPullback; backtest verdict:
    backtest_new_candidates.py TrendPullback trail +$95.79 PF 1.16/30d).
    Trend = last CLOSED H1 close vs EMA50 of H1 closes. The fn contract has
    no second timeframe, so here the H1 series is aggregated from the M15
    window in floor(n/96) buckets; the EA reads the real H1 feed
    (equivalent modulo EMA warmup depth). Entry = pullback touches EMA(21)
    and the bar closes as a rejection candle in the trend direction.
    SL 2 x ATR / TP 3 x ATR like every signal strategy."""
    if len(bars) < 262:
        return None
    a = atr(bars)
    if not a:
        return None
    nh = len(bars) // 96
    if nh < 52:
        return None
    hc = [bars[len(bars) - (nh - h) * 96 + 95]["close"] for h in range(nh)]
    trend_ema = ema(hc, 50)
    trend_ema_prev = ema(hc[:-1], 50)
    if trend_ema is None or trend_ema_prev is None:
        return None
    up = hc[-2] > trend_ema_prev
    e21 = ema([b["close"] for b in bars], 21)
    if e21 is None:
        return None
    b = bars[-1]
    px = b["close"]
    if up and b["low"] <= e21 and b["close"] > b["open"]:
        return ("entry", "buy", px - 2 * a, px + 3 * a)
    if not up and b["high"] >= e21 and b["close"] < b["open"]:
        return ("entry", "sell", px + 2 * a, px - 3 * a)
    return None


def strat_donchian(bars):
    """Donchian-20 on the HOST chart: identical engine to breakout; the H1
    host chart supplies the higher timeframe (FTTest_donchian on XAUUSD H1,
    backtest verdict: DonchianH1 trail +$47.93 PF 1.19/30d)."""
    return strat_breakout(bars)


def strat_trend(bars):
    """H1 trend + H1 momentum (EA: SigTrend, chart29-30 twins). Trend leg =
    last closed H1 close vs EMA50 of the H1 closes (same definition as
    trendpullback); momentum leg = EMA9 vs EMA21 over the recent H1 window.
    Long when both align up, short when both align down -- state-based like
    every signal strat (hold when aligned, reverse when opposed). The H1 host
    chart supplies the series, so every closed H1 bar IS a bucket. SL 2 ATR /
    TP 3 ATR per the signal convention."""
    if len(bars) < 62:
        return None
    a = atr(bars)
    if not a:
        return None
    hc = [b["close"] for b in bars]
    trend_ema = ema(hc, 50)
    if trend_ema is None:
        return None
    up = hc[-1] > trend_ema
    win = hc[-120:]
    f9, s21 = ema(win, 9), ema(win, 21)
    if f9 is None or s21 is None:
        return None
    px = bars[-1]["close"]
    if up and f9 > s21:
        return ("entry", "buy", px - 2 * a, px + 3 * a)
    if not up and f9 < s21:
        return ("entry", "sell", px + 2 * a, px - 3 * a)
    return None


def strat_supres(bars):
    """Support/Resistance rejection bounce (EA: SigSupRes, chart31-32 twins).
    S/R levels = the 200-bar window high/low forming on the M15 host chart.
    Short when a bar's high probes within 0.25 ATR of resistance but the body
    closes back below it as a bearish candle; long mirrored at support. SL
    1.5 ATR beyond the close / TP 2.5 ATR (faster mean-reversion style exit)."""
    if len(bars) < 202:
        return None
    a = atr(bars)
    if not a:
        return None
    win = 200
    hi = max(b["high"] for b in bars[-win:-1])
    lo = min(b["low"] for b in bars[-win:-1])
    b = bars[-1]
    px = b["close"]
    near = 0.25 * a
    at_res = (hi - b["high"]) <= near and b["close"] < hi - near and b["close"] < b["open"]
    at_sup = (b["low"] - lo) <= near and b["close"] > lo + near and b["close"] > b["open"]
    if at_res:
        return ("entry", "sell", px + 1.5 * a, px - 2.5 * a)
    if at_sup:
        return ("entry", "buy", px - 1.5 * a, px + 2.5 * a)
    return None


STRATS = {
    910001: {"fn": strat_breakout, "tf": "M15", "mode": "signal"},
    910002: {"fn": strat_meanrev, "tf": "M15", "mode": "signal"},
    910003: {"fn": strat_macross, "tf": "M30", "mode": "signal"},
    910004: {"fn": strat_straddle, "tf": "H1", "mode": "straddle",
             "period": "hour", "ttl": 3 * 3600},
    910005: {"fn": strat_smc, "tf": "M15", "mode": "signal"},
    910006: {"fn": strat_london, "tf": "M15", "mode": "london",
             "period": "day", "ttl": 9 * 3600},
    910007: {"fn": strat_squeeze, "tf": "M15", "mode": "signal"},
}
# order times are broker-server stamped (up to +3h vs local epoch)
SERVER_TIME_OFFSET = 3 * 3600

# Champion exit style per (symbol, strategy) from scripts/backtest_trailing_check.py
# (30d M15, all 7 strategies x 5 pairs): where trailing improved net profit the
# -T twin keeps trailing; elsewhere it holds a STATIC SL (fixed wins).
# Entries never change -- only the -T twin's exit management. straddle was
# "fixed" until 2026-10-01: the 30d sweep showed the tightest trail cuts its
# bleed $256 (-899.8 -> -641.0) so its XAU twin now trails; london stays
# fixed (fixed -$73.60 beats every trail config there).
WINNER = {
    ("AUDUSD", "breakout"): "fixed",
    ("AUDUSD", "london"): "fixed",
    ("AUDUSD", "macross"): "trail",
    ("AUDUSD", "meanrev"): "fixed",
    ("AUDUSD", "smc"): "trail",
    ("AUDUSD", "squeeze"): "trail",
    ("AUDUSD", "straddle"): "fixed",
    ("EURUSD", "breakout"): "fixed",
    ("EURUSD", "london"): "fixed",
    ("EURUSD", "macross"): "fixed",
    ("EURUSD", "meanrev"): "fixed",
    ("EURUSD", "smc"): "trail",
    ("EURUSD", "squeeze"): "trail",
    ("EURUSD", "straddle"): "fixed",
    ("GBPUSD", "breakout"): "trail",
    ("GBPUSD", "london"): "fixed",
    ("GBPUSD", "macross"): "trail",
    ("GBPUSD", "meanrev"): "fixed",
    ("GBPUSD", "smc"): "fixed",
    ("GBPUSD", "squeeze"): "fixed",
    ("GBPUSD", "straddle"): "fixed",
    ("USDJPY", "breakout"): "trail",
    ("USDJPY", "london"): "fixed",
    ("USDJPY", "macross"): "trail",
    ("USDJPY", "meanrev"): "fixed",
    ("USDJPY", "smc"): "fixed",
    ("USDJPY", "squeeze"): "trail",
    ("USDJPY", "straddle"): "fixed",
    ("XAUUSD", "breakout"): "trail",
    ("XAUUSD", "london"): "fixed",
    ("XAUUSD", "macross"): "trail",
    ("XAUUSD", "meanrev"): "fixed",
    ("XAUUSD", "smc"): "trail",
    ("XAUUSD", "squeeze"): "trail",
    ("XAUUSD", "straddle"): "trail",   # flipped 2026-10-01 (sweep: +$256/30d)
    ("XAUUSD", "fixfade"): "trail",    # new family (ex-orderflow slots)
    ("XAUUSD", "trendpullback"): "trail",
    ("XAUUSD", "donchian"): "trail",
    ("XAUUSD", "trend"): "trail",
    ("XAUUSD", "vwaprev"): "trail",    # new family (ex-supres slots)
    ("XAUUSD", "sweepabs"): "trail",   # 200d trail +$1087 PF 1.30
    ("XAUUSD", "dayopen"): "fixed",    # single fixed instance (trail grid weaker)
}

# trading table: every (symbol, strategy) pair with base magic + trailing
# twin (legacy python magics; kept only for the --check preflight listing)
_XAU_BASE = {n: 910000 + i for i, n in enumerate(STRAT_NAMES, start=1)}
TRADES = []
for _sym in SYMBOLS:
    for _i, _n in enumerate(STRAT_NAMES, start=1):
        _cfg = STRATS[_XAU_BASE[_n]]
        _base = SYMBOL_BASE[_sym] + _i
        TRADES.append({"magic": _base, "twin": _base + 10000, "symbol": _sym,
                       "name": _n, "cfg": _cfg})
TRADES_BY_SYMBOL = {}
for _t in TRADES:
    TRADES_BY_SYMBOL.setdefault(_t["symbol"], []).append(_t)


# --------------------------------------------------------------------- logging

def ensure_logs():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(DEALS_CSV):
        with open(DEALS_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=DEAL_FIELDS).writeheader()
    if not os.path.exists(EQUITY_CSV):
        with open(EQUITY_CSV, "w", newline="") as f:
            csv.writer(f).writerow(["time_utc", "balance", "equity"] +
                                   ["pnl_%s" % n for n in MAGICS.values()])
    else:
        with open(EQUITY_CSV, newline="") as f:
            first = next(csv.reader(f), None)
        if first and len(first) != 3 + len(MAGICS):
            # magics grew (multi-symbol): rewrite the header, keep old rows
            with open(EQUITY_CSV, newline="") as f:
                lines = f.readlines()
            with open(EQUITY_CSV, "w", newline="") as f:
                csv.writer(f).writerow(["time_utc", "balance", "equity"] +
                                       ["pnl_%s" % n for n in MAGICS.values()])
                f.writelines(lines[1:])
            log("equity.csv header extended to %d magic columns" % len(MAGICS))


def log_new_deals(seen, since_ts):
    # end window is +4h ahead: the broker stamps deals in server time (UTC+3),
    # which lands "in the future" vs epoch now -- without the margin the newest
    # deals were logged up to 3 hours late (dedupe makes the overlap safe).
    deals = mt5.history_deals_get(since_ts, time.time() + 4 * 3600) or []
    rows = []
    for d in deals:
        if d.ticket in seen or d.magic not in MAGICS:
            continue
        seen.add(d.ticket)
        rows.append({
            "time_utc": datetime.fromtimestamp(d.time, timezone.utc).isoformat(),
            "ticket": d.ticket, "magic": d.magic, "strategy": MAGICS[d.magic],
            "position_id": d.position_id, "symbol": d.symbol,
            "type": "buy" if d.type == mt5.DEAL_TYPE_BUY else "sell",
            "entry": "in" if d.entry == mt5.DEAL_ENTRY_IN else
                     ("out" if d.entry == mt5.DEAL_ENTRY_OUT else str(d.entry)),
            "volume": d.volume, "price": d.price,
            "commission": d.commission, "swap": d.swap, "profit": d.profit,
            "comment": d.comment,
        })
    if rows:
        with open(DEALS_CSV, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=DEAL_FIELDS).writerows(rows)
        for r in rows:
            log("  DEAL %s #%d %s %s %.2f @ %.5f pnl=%+.2f comm=%.2f" % (
                r["strategy"], r["ticket"], r["entry"], r["type"], r["volume"],
                r["price"], r["profit"], r["commission"]))
        try:
            # telegram push (one message per batch) + dashboard live tape
            import time as _t
            import live_feed
            for r in rows:
                r["_ts"] = _t.time()
            live_feed.notify(rows)
        except Exception as e:
            log("live feed skipped: %r" % e)


def snapshot_equity(seen):
    acc = mt5.account_info()
    all_deals = mt5.history_deals_get(time.time() - 30 * 86400, time.time() + 4 * 3600) or []
    with open(EQUITY_CSV, "a", newline="") as f:
        row = [datetime.now(timezone.utc).isoformat(), acc.balance, acc.equity]
        for magic in MAGICS:
            row.append(round(sum(d.profit + d.commission + d.swap
                                 for d in all_deals if d.magic == magic), 2))
        csv.writer(f).writerow(row)


# ----------------------------------------------------------------------- main

def run_loop(seen, since_ts, loops):
    # EA-ONLY RIG: the Python runner is a LOGGER -- it harvests deals into
    # deals.csv, snapshots equity.csv and reports account state. It sends no
    # orders, trails nothing, seeds nothing -- all trading lives in the EAs.
    log_new_deals(seen, since_ts)
    try:
        # ~30s-fresh live.json for the browser dashboard poll (write_live is
        # CSV-only math; uses the runner's persistent MT5 attach for prices)
        import make_dashboard
        a = mt5.account_info()
        if a is not None:
            make_dashboard.write_live(a.balance, a.equity, mt5.positions_get() or [])
    except Exception as e:
        log("live.json write skipped: %r" % e)
    try:
        # stuck-stop watchdog: broker-server lag can leave a position past its
        # SL/TP unexecuted for minutes (2026-09-29 incident). Alert Telegram
        # and auto-close once the crossing persists past the threshold.
        import stuck_stop_watchdog
        for ln in stuck_stop_watchdog.check_once(name_of=lambda m: MAGICS.get(m, str(m))):
            log(ln)
    except Exception as e:
        log("watchdog skipped: %r" % e)
    try:
        # supertrend first-close alert (one-shot) + ongoing trip log -- fired
        # the moment the new twins' first trade closes, with realized SL/TP
        # slippage vs the 2/3 ATR backtest assumption (2026-09-30 go-live)
        import st_first_trade_watch
        for ln in st_first_trade_watch.check_once(name_of=lambda m: MAGICS.get(m, str(m))):
            log(ln)
    except Exception as e:
        log("st watchdog skipped: %r" % e)
    try:
        # fixfade/vwaprev first-close alert (one-shot per family) + trip log --
        # verifies fills, 0.01 sizing and hold time vs the backtest assumptions
        # (deployed 2026-10-01 into the former orderflow/supres slots)
        import nf_first_trade_watch
        for ln in nf_first_trade_watch.check_once(name_of=lambda m: MAGICS.get(m, str(m))):
            log(ln)
    except Exception as e:
        log("newfam watchdog skipped: %r" % e)
    if loops % SNAPSHOT_EVERY == 0:
        snapshot_equity(seen)
        a = mt5.account_info()
        positions = mt5.positions_get() or []
        log("snapshot: balance=%.2f equity=%.2f open=%d"
            % (a.balance, a.equity, len(positions)))
        try:
            # live one-page dashboard, rendered by the runner so it reuses this
            # process's healthy MT5 attach (fresh ssh-spawned attaches can get
            # '-6 Authorization failed' while long-lived ones keep working)
            import make_dashboard
            make_dashboard.render(positions=positions, bal=a.balance, eq=a.equity)
        except Exception as e:
            log("dashboard render skipped: %r" % e)


def acquire_instance_lock():
    """Single-instance guard: named mutex, auto-released when the process dies."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.CreateMutexW(None, False, "Global\\FTForwardTestRunnerMutex")
        return handle != 0 and k32.GetLastError() != 183  # 183 = already exists
    except Exception:
        return True


def load_logged_tickets():
    """Tickets already in deals.csv -- so a restart never double-logs deals."""
    tickets = set()
    if os.path.exists(DEALS_CSV):
        with open(DEALS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    tickets.add(int(row["ticket"]))
                except (KeyError, ValueError):
                    pass
    return tickets


def ensure_mt5(backoff):
    """Reconnect-with-backoff when the terminal link drops (e.g. the MT5
    restart window). The symptom of a dead link is account_info() returning
    None inside run_loop, which previously surfaced as a 'NoneType' loop
    error every 30s until luck re-attached the terminal. Probe the link
    here instead: healthy -> return immediately; broken -> back off
    (5s doubling to 60s max), re-initialize with 3 quick attempts, and
    re-verify the DEMO rail before letting run_loop proceed."""
    if mt5.account_info() is not None:
        backoff["wait"] = 0
        return True
    wait = backoff.get("wait", 0)
    if wait:
        log("mt5 link down; backing off %ds before reconnect" % wait)
        time.sleep(wait)
    backoff["wait"] = min(wait * 2 if wait else 5, 60)
    mt5.shutdown()
    for _ in range(3):
        if mt5.initialize():
            acc = mt5.account_info()
            if acc is not None and acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                log("mt5 reconnected: account %s (%s) -- clean reattach"
                    % (acc.login, acc.server))
                backoff["wait"] = 0
                return True
        time.sleep(2)
    log("mt5 reconnect failed this cycle (will retry with backoff)")
    return False


def main():
    check_only = "--check" in sys.argv
    if not acquire_instance_lock():
        log("another forward-test instance is already running; exiting.")
        return 1

    # Rail 1: never auto-launch MT5
    if not mt5_running():
        log("MetaTrader 5 is NOT running. Please open it manually, then rerun.")
        log("(This script will never launch MT5 by itself.)")
        return 1

    env = load_env()
    login = env.get("login")
    if not login or not env.get("password"):
        log("No credentials in .env (need login= / password= / server=). Aborting.")
        return 1

    if not mt5.initialize():
        log("mt5.initialize() failed: %s" % (mt5.last_error(),))
        return 1

    acc = mt5.account_info()
    # Rail 2: DEMO only, unconditionally
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        log("REFUSING: account %s is NOT a demo account. Forward tests are demo-only."
            % (acc.login if acc else "?"))
        mt5.shutdown()
        return 1
    if acc.login != int(login):
        log("REFUSING: connected account %s != .env login %s." % (acc.login, login))
        mt5.shutdown()
        return 1

    symbols = []
    for s in SYMBOLS:
        try:
            symbols.append(resolve_symbol(s))
        except RuntimeError:
            log("symbol %s not found on this account -- skipping" % s)
    if not symbols:
        log("no tradable symbols found. Aborting.")
        mt5.shutdown()
        return 1
    symbols = [s for s in symbols if s in TRADES_BY_SYMBOL]  # broker-suffix safety
    log("preflight OK: demo account %s (%s) symbols=%s"
        % (acc.login, acc.server, ",".join(symbols)))

    if check_only:
        for symbol in symbols:
            for trade in TRADES_BY_SYMBOL[symbol]:
                bars = closed_bars(symbol, trade["cfg"]["tf"], 300)
                log("  %s %s (%d) %s: %d closed bars ready"
                    % (symbol, MAGICS[trade["magic"]], trade["magic"],
                       trade["cfg"]["tf"], len(bars)))
        log("check-only: no orders sent. Run without --check to start trading.")
        mt5.shutdown()
        return 0

    ensure_logs()
    seen = load_logged_tickets()          # dedupe against existing CSV
    since_ts = time.time() - 30 * 86400   # backfill 30d: catches EA trades too
    loops = 0
    log("forward test STARTED: EA-only logger mode -- %d strategies x %d symbols (%s)."
        % (len(STRAT_NAMES), len(symbols), ",".join(symbols)))
    log("  all trading is done by the MT5 EAs; this process only logs deals/equity.")
    backoff = {"wait": 0}
    try:
        while True:
            loops += 1
            try:
                if not ensure_mt5(backoff):
                    time.sleep(LOOP_SEC)
                    continue
                run_loop(seen, since_ts, loops)
            except Exception as e:  # one bad loop must not kill the whole run
                log("loop error (will retry): %r" % e)
            time.sleep(LOOP_SEC)
    except KeyboardInterrupt:
        log("stopped by user. Positions left as-is (SL/TP protects them).")
    finally:
        log_new_deals(seen, since_ts)
        snapshot_equity(seen)
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
