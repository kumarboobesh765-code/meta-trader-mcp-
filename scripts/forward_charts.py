"""Generate the forward-test dashboard from logs/forward/ (deals.csv + equity.csv).

Charts (written to charts/):
  01_equity_by_strategy.png   cumulative realized P&L per strategy stream
  02_daily_pnl.png            grouped daily P&L bars per stream
  03_drawdown.png             drawdown per stream over time
  04_forward_vs_backtest.png  win rate & profit factor per stream
  05_champion_exits.png       champion exit style (trail/fixed) grid

Streams are derived from forward_test.MAGICS -- the EA-only rig's full stream
list: 7 XAUUSD FTTest EAs x2 twins (9300xx/9400xx), FTTestMultiEA on 4 FX
pairs x7 strategies x2 twins (931000+/-934000 bases +20000/+30000), the
AetherFlowEA twins (950001/960001 M15 confluence, 950002/960002 M30 UT-only)
and the SMVP scalper (26092501). The runner only LOGS these -- all trading
lives in the EAs.

Usage: python scripts/forward_charts.py [log_dir]
       (log_dir defaults to logs/forward; the watchdog passes the pulled dir)
"""

import csv
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs", "forward")
if len(sys.argv) > 1:  # watchdog points this at the pulled VPS logs
    LOG_DIR = os.path.abspath(sys.argv[1])
CHART_DIR = os.path.join(ROOT, "charts")
DEALS_CSV = os.path.join(LOG_DIR, "deals.csv")

# Every stream name the logger can ever write: the runner imports its magic
# map straight from forward_test.py, so charts stay in sync with the rig
# automatically (20 MT5 charts -> 75 EA streams, incl. smvp + 4 aetherflow).
from forward_test import MAGICS as ALL_MAGICS  # noqa: E402
# The runner's own legacy magics are still in MAGICS but never traded since
# the EA-only switch: python XAU streams (9100xx/9200xx) AND python FX
# streams (9110xx/9210xx etc.). Their names never contain "-EA"; every real
# EA stream does (FTTestEA / FTTestMultiEA / AetherFlowEA) except smvp.
_PY_STRATS = ("breakout", "meanrev", "macross", "straddle", "smc",
              "london", "squeeze")
LEGACY = {n for n in ALL_MAGICS.values()
          if any(n == s or n == s + "-T" or n.startswith(s + "-")
                 for s in _PY_STRATS) and "-EA" not in n}
STRATS = sorted(set(ALL_MAGICS.values()) - LEGACY)

PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
           "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#aec7e8", "#ffbb78",
           "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7",
           "#dbdb8d", "#9edae5", "#393b79", "#637939", "#8c6d31", "#843c39",
           "#ad494a", "#d6616b", "#7f4d24", "#9d755d", "#e7969c", "#7b4173",
           "#3182bd", "#31a354", "#756bb1", "#636363", "#6baed6", "#74c476",
           "#9e9ac8", "#969696", "#de9ed6", "#ce6dbd", "#b5cf6b", "#bd9e39"]
COLORS = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(STRATS)}


def color_of(s):
    return COLORS[s]


def style_of(s):
    return "--" if s.endswith("-T") else "-"  # dashed = trailing-SL twin


# Champion exit style per (base strategy, symbol) -- mirrored from
# forward_test.py WINNER (scripts/backtest_trailing_check.py verdict matrix,
# 30d trailing-vs-fixed backtest). Governs how each -T stream is managed.
CHAMP = {
    "breakout": {"XAUUSD": "trail", "EURUSD": "fixed", "GBPUSD": "trail",
                 "USDJPY": "trail", "AUDUSD": "fixed"},
    "meanrev":  {"XAUUSD": "fixed", "EURUSD": "fixed", "GBPUSD": "fixed",
                 "USDJPY": "fixed", "AUDUSD": "fixed"},
    "macross":  {"XAUUSD": "trail", "EURUSD": "fixed", "GBPUSD": "trail",
                 "USDJPY": "trail", "AUDUSD": "trail"},
    "straddle": {"XAUUSD": "fixed", "EURUSD": "fixed", "GBPUSD": "fixed",
                 "USDJPY": "fixed", "AUDUSD": "fixed"},
    "smc":      {"XAUUSD": "trail", "EURUSD": "trail", "GBPUSD": "fixed",
                 "USDJPY": "fixed", "AUDUSD": "trail"},
    "london":   {"XAUUSD": "fixed", "EURUSD": "fixed", "GBPUSD": "fixed",
                 "USDJPY": "fixed", "AUDUSD": "fixed"},
    "squeeze":  {"XAUUSD": "trail", "EURUSD": "trail", "GBPUSD": "fixed",
                 "USDJPY": "trail", "AUDUSD": "trail"},
}
SYMS = ["XAUUSD"]   # XAU-only rig (2026-09-28): FX panels retired
_SYMBOL_OF = {"EUR": "EURUSD", "GBP": "GBPUSD", "JPY": "USDJPY", "AUD": "AUDUSD"}
# AetherFlow twin pairs' verdicts from scripts/backtest_aetherflow.py
# (30d windows; M30 90d: both twins lose, trail relatively better -> A/B only).
AETHER_CHAMP = {"aetherflow": "fixed",        # 950001 M15 confluence (filter blocks UT winners)
                "aetherflow-T": "trail",      # 960001 M15 confluence trailing
                "aetherflow-M30": "fixed",    # 950002 M30 UT-only (90d: A/B baseline)
                "aetherflow-M30-T": "trail"}  # 960002 M30 UT-only trailing


def champ_style(s):
    """'trail' / 'fixed' for a -T stream name, None for fixed-twin streams."""
    if s in AETHER_CHAMP:
        return AETHER_CHAMP[s] if s.endswith("-T") else None
    if not s.endswith("-T"):
        return None
    base, sym = s[:-2], "XAUUSD"
    if base.endswith("-EA"):  # MultiEA/FTTestEA twins carry an -EA infix
        base = base[:-3]
    for code, sy in _SYMBOL_OF.items():
        if base.endswith("-" + code):
            base, sym = base[: -(len(code) + 1)], sy
            break
    return CHAMP.get(base, {}).get(sym, "trail")


def legend_label(s):
    st = champ_style(s)
    return "%s [%s]" % (s, st) if st else s


def short_label(s):
    """Shorter legend text so 42 streams stay readable."""
    return (s.replace("-XAUUSD", "").replace("-EA-T", " EA-T")
             .replace("-EA", " EA").replace("-T", " T") if "-XAUUSD" not in s
             else s.replace("-XAUUSD-EA-T", " EA-T").replace("-XAUUSD-EA", " EA")
             .replace("-XAUUSD-T", " T").replace("-XAUUSD", ""))


# Backtest reference (ATR Donchian breakout, XAUUSD H1, 0.01 lot, Jan-Sep 2026):
# 202 trades, 40.6% win rate, profit factor 1.00, max DD $927.50.
BT_WR, BT_PF = 40.6, 1.00


def load_deals():
    if not os.path.exists(DEALS_CSV):
        return []
    with open(DEALS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("volume", "price", "commission", "swap", "profit"):
            r[k] = float(r[k] or 0)
    return rows


def closed_trades(deals):
    """One P&L figure per position: sum of profit+commission+swap on its deals,
    timestamped at the out deal (realized)."""
    per_pos = defaultdict(lambda: {"net": 0.0, "t": None, "strategy": None})
    for d in deals:
        p = per_pos[d["position_id"]]
        p["net"] += d["profit"] + d["commission"] + d["swap"]
        p["strategy"] = d["strategy"]
        if d["entry"] == "out":
            p["t"] = d["time_utc"]
    return [(v["t"], v["strategy"], round(v["net"], 2))
            for v in per_pos.values() if v["t"] is not None]


def cum_series(trades):
    """{strategy: ([times], [cumulative pnl])} sorted by close time."""
    by = defaultdict(list)
    for t, s, net in trades:
        by[s].append((t, net))
    out = {}
    for s, rows in by.items():
        rows.sort()
        cum, c = [], 0.0
        for _, net in rows:
            c += net
            cum.append(round(c, 2))
        out[s] = ([r[0] for r in rows], cum)
    return out


def _finish(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, name + ".png"), dpi=110)
    plt.close(fig)


def chart_equity(series):
    fig, ax = plt.subplots(figsize=(12.5, 6.5))
    plotted = []
    for s in STRATS:
        if s not in series:
            continue
        xs, ys = series[s]
        ax.plot(range(len(ys)), ys, label=legend_label(s), color=color_of(s),
                linestyle=style_of(s), linewidth=1.5)
        plotted.append(s)
    ax.set_title("Forward test: cumulative realized P&L per strategy stream (EA-only rig, 0.01 lot)")
    ax.set_xlabel("closed trade #")
    ax.set_ylabel("P&L incl. commission + swap (USD)")
    ax.grid(True, alpha=0.3)
    if plotted:
        ax.legend(fontsize=7, ncol=3)
    else:
        ax.text(0.5, 0.5, "no closed trades yet", ha="center", va="center",
                transform=ax.transAxes)
    _finish(fig, "01_equity_by_strategy")


def chart_daily(trades):
    daily = defaultdict(lambda: defaultdict(float))
    for t, s, net in trades:
        daily[t[:10]][s] += net
    fig, ax = plt.subplots(figsize=(12.5, 6.5))
    days = sorted(daily)
    if days:
        shown = [s for s in STRATS if any(daily[d].get(s, 0.0) for d in days)]
        width = 0.8 / max(1, len(shown))
        xs = range(len(days))
        for i, s in enumerate(shown):
            vals = [daily[d].get(s, 0.0) for d in days]
            ax.bar([x + i * width for x in xs], vals, width=width,
                   label=s, color=color_of(s),
                   hatch="//" if s.endswith("-T") else None,
                   edgecolor="white", linewidth=0.3)
        ax.set_xticks([x + 0.4 for x in xs])
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8)
        ax.legend(fontsize=7, ncol=3)
    else:
        ax.text(0.5, 0.5, "no closed trades yet", ha="center", va="center",
                transform=ax.transAxes)
    ax.set_title("Forward test: daily realized P&L per strategy stream")
    ax.set_ylabel("P&L (USD)")
    ax.grid(True, axis="y", alpha=0.3)
    _finish(fig, "02_daily_pnl")


def chart_drawdown(series):
    fig, ax = plt.subplots(figsize=(12.5, 6.5))
    plotted = False
    for s in STRATS:
        if s not in series:
            continue
        ys = series[s][1]
        peak, dd = -1e9, []
        for v in ys:
            peak = max(peak, v)
            dd.append(v - peak)
        ax.plot(range(len(dd)), dd, label=s, color=color_of(s),
                linestyle=style_of(s), linewidth=1.5)
        plotted = True
    ax.set_title("Forward test: drawdown per strategy stream (real spread, news, slippage)")
    ax.set_xlabel("closed trade #")
    ax.set_ylabel("drawdown from peak (USD)")
    ax.grid(True, alpha=0.3)
    if plotted:
        ax.legend(fontsize=7, ncol=3)
    else:
        ax.text(0.5, 0.5, "no closed trades yet", ha="center", va="center",
                transform=ax.transAxes)
    _finish(fig, "03_drawdown")


def chart_vs_backtest(trades):
    stats = {}
    for s in STRATS:
        rows = [(t, net) for t, ss, net in trades if ss == s]
        n = len(rows)
        if n == 0:
            continue
        wins = [net for _, net in rows if net > 0]
        losses = [net for _, net in rows if net <= 0]
        wr = 100.0 * len(wins) / n
        gp = sum(wins)
        gl = abs(sum(losses))
        pf = gp / gl if gl > 0 else float("inf") if gp > 0 else 0.0
        stats[s] = (n, wr, min(pf, 10.0))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.5))
    names = [s for s in STRATS if s in stats]
    if names:
        xs = range(len(names))
        ax1.bar(xs, [stats[s][1] for s in names],
                color=[color_of(s) for s in names],
                hatch=["//" if s.endswith("-T") else None for s in names],
                edgecolor="white", linewidth=0.3)
        ax1.axhline(BT_WR, color="black", linestyle="--", linewidth=1,
                    label="backtest ref %.1f%%" % BT_WR)
        ax1.set_xticks(list(xs))
        ax1.set_xticklabels([short_label(s) for s in names], rotation=45,
                            ha="right", fontsize=7)
        ax1.set_title("Win rate, forward (live conditions)")
        ax1.set_ylabel("%")
        ax1.legend()

        ax2.bar(xs, [stats[s][2] for s in names],
                color=[color_of(s) for s in names],
                hatch=["//" if s.endswith("-T") else None for s in names],
                edgecolor="white", linewidth=0.3)
        ax2.axhline(BT_PF, color="black", linestyle="--", linewidth=1,
                    label="backtest ref %.2f" % BT_PF)
        ax2.set_xticks(list(xs))
        ax2.set_xticklabels([short_label(s) for s in names], rotation=45,
                            ha="right", fontsize=7)
        ax2.set_title("Profit factor, forward (live conditions)")
        ax2.legend()

        note = "trades: " + ", ".join("%s=%d" % (short_label(s), stats[s][0])
                                      for s in names)
        fig.suptitle("Forward vs backtest -- " + note, fontsize=10)
    else:
        for ax in (ax1, ax2):
            ax.text(0.5, 0.5, "no closed trades yet", ha="center", va="center",
                    transform=ax.transAxes)
    _finish(fig, "04_forward_vs_backtest")


def chart_champion():
    """Grid of the champion exit style (trail/fixed) for every strategy x symbol
    row, plus the AetherFlow twin pairs."""
    fig, ax = plt.subplots(figsize=(9, 4.8))
    names = list(CHAMP)
    syms = SYMS
    for yi, name in enumerate(names):
        for xi, s in enumerate(syms):
            st = CHAMP[name][s]
            ax.add_patch(plt.Rectangle((xi, len(names) - 1 - yi), 0.94, 0.9,
                                       color="#2e7d32" if st == "trail" else "#616161",
                                       alpha=0.9))
            ax.text(xi + 0.47, len(names) - 1 - yi + 0.45, st, ha="center",
                    va="center", color="white", fontsize=9)
    for yi, (name, st) in enumerate(AETHER_CHAMP.items(),
                                    start=len(names)):
        ax.add_patch(plt.Rectangle((0, len(names) + len(AETHER_CHAMP) - 1 - yi),
                                   0.94, 0.9,
                                   color="#2e7d32" if st == "trail" else "#616161",
                                   alpha=0.9))
        ax.text(0.47, len(names) + len(AETHER_CHAMP) - 1 - yi + 0.45, st,
                ha="center", va="center", color="white", fontsize=9)
    ax.set_xlim(0, len(syms))
    ax.set_ylim(0, len(names) + len(AETHER_CHAMP))
    ax.set_xticks([x + 0.47 for x in range(len(syms))])
    ax.set_xticklabels(syms, fontsize=9)
    ax.set_yticks([len(names) + len(AETHER_CHAMP) - 1 - y + 0.45
                   for y in range(len(names) + len(AETHER_CHAMP))])
    ax.set_yticklabels(names + list(AETHER_CHAMP), fontsize=9)
    ax.set_title("Champion exit style for the -T twin (30d trailing-vs-fixed verdict)")
    _finish(fig, "05_champion_exits")


def stream_status(trades, deals):
    """One row per expected stream: closed-trade count, realized net, last deal.
    Covers ALL streams the EAs can produce -- also the ones with no trades yet."""
    n_trades = defaultdict(int)
    net = defaultdict(float)
    last = {}
    for _, s, n in trades:
        n_trades[s] += 1
        net[s] += n
    n_deals = defaultdict(int)
    for d in deals:
        s = d.get("strategy") or "?"
        n_deals[s] += 1
        last[s] = max(last.get(s, ""), d.get("time_utc", ""))
    rows = []
    for s in STRATS:
        rows.append((s, n_deals[s], n_trades[s], round(net[s], 2), last.get(s, "")))
    return rows


def load_equity():
    """(last_row, day_start_row) from equity.csv -- rows as dicts; empty dicts
    when the file is missing/short."""
    path = os.path.join(LOG_DIR, "equity.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("time_utc")]
    if not rows:
        return {}, {}
    today = rows[-1]["time_utc"][:10]
    day_rows = [r for r in rows if r["time_utc"][:10] == today]
    return rows[-1], (day_rows[0] if day_rows else rows[0])


_SYMBOL_CODES = ("EUR", "GBP", "JPY", "AUD")


def family_of(stream):
    """'breakout-EUR-EA-T' -> 'breakout'; 'smvp' -> 'smvp';
    'aetherflow-M30-T' -> 'aetherflow'. Collapses twins + symbols."""
    s = stream[:-2] if stream.endswith("-T") else stream
    s = s[:-3] if s.endswith("-EA") else s
    if s.endswith(_SYMBOL_CODES) and s[-4] == "-":
        s = s[:-4]
    if s == "aetherflow-M30":
        s = "aetherflow"
    return s


def symbol_of(stream):
    """Rough symbol attribution for a stream name (for the per-symbol view)."""
    for code, sym in _SYMBOL_OF.items():
        if "-%s-" % code in stream or stream.endswith("-" + code):
            return sym
    return "XAUUSD"  # bare -EA streams, smvp, aetherflow


def pnl_summary(trades):
    """({'family': (net, n_trades)}, {'symbol': (net, n_trades)}) from closed
    trades, twins combined."""
    fam, sym = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
    for _, s, net in trades:
        f = family_of(s)
        fam[f][0] += net
        fam[f][1] += 1
        y = symbol_of(s)
        sym[y][0] += net
        sym[y][1] += 1
    return (dict(sorted(fam.items(), key=lambda kv: -kv[1][0])),
            dict(sorted(sym.items(), key=lambda kv: -kv[1][0])))


def summary_html(trades, eq_last, eq_day0):
    """Account snapshot panel + strategy-family and per-symbol P&L rankings."""
    import html as _html
    out = "<h2>Account summary</h2>"
    if eq_last:
        bal = float(eq_last.get("balance") or 0)
        eqt = float(eq_last.get("equity") or 0)
        d0_bal = float(eq_day0.get("balance") or 0) if eq_day0 else bal
        d0_eq = float(eq_day0.get("equity") or 0) if eq_day0 else eqt
        float_pnl = eqt - bal
        day_bal = bal - d0_bal
        day_eq = eqt - d0_eq
        day = eq_last["time_utc"][:16].replace("T", " ")
        col = lambda v: ("#81c784" if v >= 0 else "#e57373")
        out += ("<table style='border-collapse:collapse;font-size:13px'>"
                "<tr><td style='opacity:.7;padding:2px 14px 2px 0'>balance</td>"
                "<td style='padding:2px 18px 2px 0'><b>$%s</b></td>"
                "<td style='opacity:.7;padding:2px 14px 2px 0'>equity</td>"
                "<td style='padding:2px 18px 2px 0'><b>$%s</b></td></tr>"
                "<tr><td style='opacity:.7'>floating P&amp;L</td>"
                "<td style='color:%s'>%+.2f</td>"
                "<td style='opacity:.7'>today (balance / equity)</td>"
                "<td><span style='color:%s'>%+.2f</span> / "
                "<span style='color:%s'>%+.2f</span></td></tr>"
                "<tr><td style='opacity:.7'>snapshot</td><td colspan='3' "
                "style='opacity:.55'>%s UTC</td></tr></table>"
                % ("{:,.2f}".format(bal), "{:,.2f}".format(eqt),
                   col(float_pnl), float_pnl, col(day_bal), day_bal,
                   col(day_eq), day_eq, day))
    else:
        out += "<p style='opacity:.6'>no equity snapshots yet</p>"
    fam, sym = pnl_summary(trades)
    if fam:
        def table(title, d):
            t = "<h2>%s</h2><table style='border-collapse:collapse;font-size:12px'>" \
                "<tr style='opacity:.7'><th align='left'>%s</th><th>closed</th>" \
                "<th>net $</th></tr>" % (title, title.split(" ")[0])
            for k, (net, n) in d.items():
                c = "#81c784" if net >= 0 else "#e57373"
                t += ("<tr><td>%s</td><td align='center'>%d</td>"
                      "<td align='right' style='color:%s'>%+.2f</td></tr>"
                      % (_html.escape(k), n, c, net))
            return t + "</table>"
        out += "<div style='display:flex;gap:40px;flex-wrap:wrap'>" \
               + table("Strategy families (twins combined)", fam) \
               + table("Per symbol (EA streams)", sym) + "</div>"
    return out


# ---------------------------------------------------------------- trail A/B
def closed_positions(deals):
    """[(strategy, entry_t, exit_t, net)] -- one record per closed position."""
    per = defaultdict(lambda: {"in": None, "out": None, "net": 0.0,
                               "strategy": None})
    for d in deals:
        p = per[d["position_id"]]
        p["net"] += d["profit"] + d["commission"] + d["swap"]
        p["strategy"] = d["strategy"]
        if d["entry"] == "in" and (p["in"] is None or d["time_utc"] < p["in"]):
            p["in"] = d["time_utc"]
        if d["entry"] == "out":
            p["out"] = d["time_utc"]
    return [(v["strategy"], v["in"], v["out"], round(v["net"], 2))
            for v in per.values()
            if v["out"] is not None and v["in"] is not None]


def twin_pairs():
    """[(fixed_name, trail_name)] for every twin pair in STRATS."""
    sset = set(STRATS)
    out = []
    for s in STRATS:
        if s.endswith("-T") or s == "smvp":
            continue
        if s + "-T" in sset:
            out.append((s, s + "-T"))
    return sorted(out)


def trail_ab(positions):
    """Match twin trades by entry time (twins fill the same second from the
    same signal). Returns [(fixed_name, matches, fixed_sum, trail_sum)] with
    matches = [(entry_t, fixed_net, trail_net)]."""
    by = defaultdict(dict)
    for strat, tin, _tout, net in positions:
        by[strat][tin] = net
    rows = []
    for f, t in twin_pairs():
        fd, td = by.get(f, {}), by.get(t, {})
        common = sorted(set(fd) & set(td))
        if not common:
            continue
        matches = [(k, fd[k], td[k]) for k in common]
        rows.append((f, matches, sum(m[1] for m in matches),
                     sum(m[2] for m in matches)))
    return rows


def chart_trail_ab(ab):
    fig, ax = plt.subplots(figsize=(12.5, 5.5))
    plotted = False
    for i, (name, matches, _fs, _ts) in enumerate(ab):
        if len(matches) < 2:
            continue
        cum, c = [], 0.0
        for _k, fn, tn in matches:
            c += tn - fn
            cum.append(round(c, 2))
        ax.plot(range(1, len(cum) + 1), cum, marker="o", markersize=3,
                label="%s (n=%d)" % (name, len(matches)),
                color=PALETTE[i % len(PALETTE)], linewidth=1.6)
        plotted = True
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("Trailing vs fixed twin: cumulative P&L edge per matched trade")
    ax.set_xlabel("matched trade #")
    ax.set_ylabel("trail - fixed (USD)")
    ax.grid(True, alpha=0.3)
    if plotted:
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "no matched twin trades yet", ha="center", va="center",
                transform=ax.transAxes)
    _finish(fig, "06_trail_vs_fixed")


def trail_ab_html(ab):
    """Summary table per pair + the most recent matched trades trade-by-trade."""
    import html as _html
    if not ab:
        return ""
    summ = ("<h2>Trail vs fixed A/B (realized, matched by entry)</h2>"
            "<table style='border-collapse:collapse;font-size:12px'>"
            "<tr style='opacity:.7'><th align='left'>pair (fixed vs -T)</th>"
            "<th>matched</th><th>fixed $</th><th>trail $</th><th>edge</th>"
            "<th>trail wins</th></tr>")
    for name, matches, fs, ts in ab:
        wins = sum(1 for _k, fn, tn in matches if tn > fn)
        summ += ("<tr><td>%s</td><td align='center'>%d</td>"
                 "<td align='right'>%+.2f</td><td align='right'>%+.2f</td>"
                 "<td align='right' style='color:%s'>%+.2f</td>"
                 "<td align='center'>%d/%d</td></tr>"
                 % (_html.escape(name), len(matches), fs, ts,
                    "#81c784" if ts - fs >= 0 else "#e57373", ts - fs,
                    wins, len(matches)))
    summ += "</table>"
    recent = []
    for name, matches, _fs, _ts in ab:
        for k, fn, tn in matches:
            recent.append((k, name, fn, tn))
    recent.sort(reverse=True)
    if recent:
        det = ("<h2>Recent twin exits, trade by trade</h2>"
               "<table style='border-collapse:collapse;font-size:12px'>"
               "<tr style='opacity:.7'><th>entry (UTC)</th>"
               "<th align='left'>pair</th><th>fixed $</th><th>trail $</th>"
               "<th>edge</th></tr>")
        for k, name, fn, tn in recent[:12]:
            det += ("<tr><td>%s</td><td>%s</td><td align='right'>%+.2f</td>"
                    "<td align='right'>%+.2f</td>"
                    "<td align='right' style='color:%s'>%+.2f</td></tr>"
                    % (k[:16].replace("T", " "), _html.escape(name),
                       fn, tn, "#81c784" if tn - fn >= 0 else "#e57373",
                       tn - fn))
        det += "</table>"
    else:
        det = ""
    return summ + det


def write_dashboard(trades, status, eq_last=None, eq_day0=None, ab=None):
    import base64
    import html as _html
    rows = ""
    for name in ("01_equity_by_strategy", "02_daily_pnl", "03_drawdown",
                 "04_forward_vs_backtest", "05_champion_exits",
                 "06_trail_vs_fixed"):
        with open(os.path.join(CHART_DIR, name + ".png"), "rb") as f:
            uri = base64.b64encode(f.read()).decode()
        rows += ('<div><h2>%s</h2><img src="data:image/png;base64,%s"></div>\n'
                 % (name, uri))
    banner = ""
    if not trades:
        banner = ('<div style="background:#5d4037;border:1px solid #ffb74d;'
                  'border-radius:6px;padding:10px 16px;margin-bottom:14px">'
                  '<b>No closed trades yet.</b> The rig is EA-only and live on the '
                  'Vantage demo; deals.csv fills up as the EAs trade (first fills '
                  'expected Monday at the gold open). Charts and the stream table '
                  'below will populate automatically.</div>')
    status_html = ""
    if status:
        tbl = ("<table style='border-collapse:collapse;font-size:12px'>"
               "<tr style='opacity:.7'><th align='left'>stream</th>"
               "<th>deals</th><th>closed trades</th><th>net $</th>"
               "<th align='left'>last deal (UTC)</th></tr>")
        for s, nd, nt, n, ts in status:
            active = " style='color:#81c784'" if nd else " style='opacity:.55'"
            tbl += (f"<tr{active}><td>{_html.escape(s)}</td>"
                    f"<td align='center'>{nd}</td>"
                    f"<td align='center'>{nt}</td>"
                    f"<td align='right'>{n:+.2f}</td>"
                    f"<td>{_html.escape(ts)}</td></tr>")
        tbl += "</table>"
        status_html = ("<h2>Stream status (all %d EA streams)</h2>" % len(status)
                       + tbl)
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta http-equiv='refresh' content='60'>"
            "<title>Forward test dashboard (EA-only rig)</title>"
            "<style>body{font-family:sans-serif;background:#111;color:#eee;margin:20px}"
            "img{max-width:100%%;background:#fff;border-radius:6px}"
            "table td,table th{padding:3px 10px;border-bottom:1px solid #333}</style>"
            "</head><body>"
            "<h1>Forward test -- %d closed trades (24 charts, EA-only rig)</h1>"
            "%s%s%s%s%s"
            "</body></html>" % (len(trades), banner, rows,
                                summary_html(trades, eq_last, eq_day0),
                                trail_ab_html(ab or []), status_html))
    with open(os.path.join(CHART_DIR, "dashboard.html"), "w") as f:
        f.write(html)


def main():
    os.makedirs(CHART_DIR, exist_ok=True)
    deals = load_deals()
    trades = closed_trades(deals)
    series = cum_series(trades)
    chart_equity(series)
    chart_daily(trades)
    chart_drawdown(series)
    chart_vs_backtest(trades)
    chart_champion()
    status = stream_status(trades, deals)
    eq_last, eq_day0 = load_equity()
    ab = trail_ab(closed_positions(deals))
    chart_trail_ab(ab)
    write_dashboard(trades, status, eq_last, eq_day0, ab)
    print("charts written to charts/ (%d closed trades so far, %d streams tracked)"
          % (len(trades), len(status)))
    if ab:
        print("\ntrail-vs-fixed A/B (matched by entry):")
        for name, matches, fs, ts in ab:
            print("  %-22s n=%-3d fixed %+.2f  trail %+.2f  edge %+.2f"
                  % (name, len(matches), fs, ts, ts - fs))
    fam, sym = pnl_summary(trades)
    if fam:
        print("\nstrategy families (twins combined, realized):")
        for k, (net, n) in fam.items():
            print("  %-12s %3d trades  net %+.2f" % (k, n, net))
    if sym:
        print("per symbol (EA streams):")
        for k, (net, n) in sym.items():
            print("  %-8s %3d trades  net %+.2f" % (k, n, net))
    for s, nd, nt, n, _ in status:
        if nd:
            print("  %-22s deals %3d  closed %3d  net %+.2f" % (s, nd, nt, n))
    idle = [s for s, nd, _, _, _ in status if not nd]
    if idle:
        print("  (no deals yet: %s)" % ", ".join(idle[:8]) +
              (" ... +%d more" % (len(idle) - 8) if len(idle) > 8 else ""))


if __name__ == "__main__":
    main()
