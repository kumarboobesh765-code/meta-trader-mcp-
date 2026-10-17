r"""One-page HTML dashboard for the FTTest rig.
Reads deals.csv + live positions, renders self-contained dark HTML (no
external assets) to C:\FTTest\logs\dashboard.html.

Two modes:
  1. imported by forward_test.py -- render(positions, bal, eq) is called by
     the runner inside its snapshot cycle (the runner owns the healthy MT5
     attach, so the dashboard gets live data with zero extra attaches)
  2. standalone: python make_dashboard.py [--loop N] -- attaches to MT5 itself
"""
import csv
import html
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

LOG = r"C:\FTTest\logs"
DEALS = os.path.join(LOG, "forward", "deals.csv")
EQUITY = os.path.join(LOG, "forward", "equity.csv")
OUT = os.path.join(LOG, "dashboard.html")
LIVE = os.path.join(LOG, "live.json")

# EA registry: stream name -> (chart, kind, exit style)
# kind: core signal / standalone / aether; exit: fixed / trail / mixed (SMVP)
STREAMS = {
    "breakout-EA": (1, "FTTest_breakout", "fixed"), "breakout-EA-T": (2, "FTTest_breakout", "trail"),
    # meanrev charts 3/4 retired 2026-09-30 -- slots unused
    "macross-EA": (5, "FTTest_macross", "fixed"), "macross-EA-T": (6, "FTTest_macross", "trail"),
    "straddle-EA": (7, "FTTest_straddle", "fixed"), "straddle-EA-T": (8, "FTTest_straddle", "trail"),  # T flipped ON 10/01
    "smc-EA": (9, "FTTest_smc", "fixed"), "smc-EA-T": (10, "FTTest_smc", "trail"),
    "london-EA": (11, "FTTest_london", "fixed"), "london-EA-T": (12, "FTTest_london", "fixed"),
    "squeeze-EA": (5, "FTTest_squeeze", "fixed"), "squeeze-EA-T": (13, "FTTest_squeeze", "trail"),
    "smvp": (16, "XAUUSD_SmartMoney_VolumeProfile_EA", "mixed"),
    # profile charts 21/22 retired 2026-09-30 -- slots unused
    "fixfade-EA": (23, "FTTest_fixfade", "fixed"), "fixfade-EA-T": (24, "FTTest_fixfade", "trail"),   # repurposed from orderflow 10/01
    # trendpullback charts 25/26 retired 2026-10-01 (round-2 executor)
    "donchian-EA": (27, "FTTest_donchian", "fixed"), "donchian-EA-T": (28, "FTTest_donchian", "trail"),
    "trend-EA": (29, "FTTest_trend", "fixed"), "trend-EA-T": (30, "FTTest_trend", "trail"),
    "vwaprev-EA": (31, "FTTest_vwaprev", "fixed"), "vwaprev-EA-T": (32, "FTTest_vwaprev", "trail"),   # repurposed from supres 10/01
    "supertrend-EA": (35, "FTTest_supertrend", "fixed"), "supertrend-EA-T": (36, "FTTest_supertrend", "trail"),
    "liquiditysweep-EA": (38, "FTTest_liquiditysweep", "fixed"),
    "liquiditysweep-BIN": (37, "LiquiditySweepH4", "mixed"),
    "dayopen-EA": (39, "FTTest_dayopen", "fixed"),   # added 2026-10-02
    "aetherflow": (17, "AetherFlowEA", "fixed"), "aetherflow-T": (18, "AetherFlowEA", "trail"),
    "aetherflow-M30": (19, "AetherFlowEA", "fixed"), "aetherflow-M30-T": (20, "AetherFlowEA", "trail"),
    "aetherflow-H4": (33, "AetherFlowEA", "fixed"), "aetherflow-H4-T": (34, "AetherFlowEA", "trail"),
}


def family(stream):
    s = stream
    if s.endswith("-T"):
        s = s[:-2]
    if s.endswith("-EA"):
        s = s[:-3]
    return {"breakout": "breakout", "macross": "macross",
            "straddle": "straddle", "smc": "smc", "london": "london",
            "squeeze": "squeeze", "fixfade": "fixfade",
            "donchian": "donchian",
            "trend": "trend", "vwaprev": "vwaprev", "supertrend": "supertrend", "smvp": "smvp",
            "dayopen": "dayopen",
            "liquiditysweep": "liquiditysweep", "liquiditysweep-BIN": "liquiditysweep",
            "aetherflow-M30": "aetherflow", "aetherflow-H4": "aetherflow"}.get(s, s)


def parse_utc(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def load_deals():
    """Return (per-stream closed-trip stats, last activity per stream, trades since 00:00 UTC)."""
    trips = defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0, "last": None})
    today_net = defaultdict(float)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(DEALS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["entry"] != "out":
                continue
            st = row["strategy"]
            pnl = float(row["profit"] or 0) + float(row["commission"] or 0) + float(row["swap"] or 0)
            t = trips[st]
            t["n"] += 1
            t["net"] += pnl
            t["wins"] += 1 if pnl > 0 else 0
            ts = parse_utc(row["time_utc"])
            if ts:
                if t["last"] is None or ts > t["last"]:
                    t["last"] = ts
                if row["time_utc"][:10] == day:
                    today_net[st] += pnl
    return trips, today_net


def load_equity():
    bal = eq = 0.0
    ts = None
    with open(EQUITY, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0] == "time_utc":
                continue
            try:
                bal, eq = float(row[1]), float(row[2])
                ts = row[0]
            except (ValueError, IndexError):
                pass
    return bal, eq, ts


def magics_of(stream):
    return {930000 + i: n for i, n in enumerate([])}


MAGIC_HINT = {
    "breakout-EA": "930001", "breakout-EA-T": "940001", "macross-EA": "930003",
    "macross-EA-T": "940003",
    "straddle-EA": "930004", "straddle-EA-T": "940004", "smc-EA": "930005",
    "smc-EA-T": "940005", "london-EA": "930006", "london-EA-T": "940006",
    "squeeze-EA": "930007", "squeeze-EA-T": "940007", "smvp": "26092501",
    "fixfade-EA": "930009",
    "fixfade-EA-T": "940009",
    "donchian-EA": "930011", "donchian-EA-T": "940011", "trend-EA": "930012",
    "trend-EA-T": "940012", "vwaprev-EA": "930013", "vwaprev-EA-T": "940013",
    "supertrend-EA": "930014", "supertrend-EA-T": "940014",
    "liquiditysweep-EA": "930015", "liquiditysweep-BIN": "930016",
    "dayopen-EA": "930017",
    "aetherflow": "950001", "aetherflow-T": "960001", "aetherflow-M30": "950002",
    "aetherflow-M30-T": "960002", "aetherflow-H4": "950003", "aetherflow-H4-T": "960003",
}


def write_live(bal, eq, positions):
    """Lightweight per-loop live.json refresh (no full page render).
    Called by the runner every loop so the browser polling sees ~30s-fresh
    numbers between 5-minute page rebuilds."""
    trips, today_net = load_deals()
    day = sum(today_net.values())
    tot = sum(t["net"] for t in trips.values())
    flt = 0.0
    for p in positions or []:
        flt += getattr(p, "profit", 0) if not isinstance(p, dict) else p.get("pnl", 0.0)
    n_open = len(list(positions or []))
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    live = {
        "gen": gen, "bal": "%.2f" % bal, "eq": "%.2f" % eq,
        "closed": "%+.2f" % tot, "day": "%+.2f" % day,
        "open": str(n_open), "flt": "%+.2f" % flt,
        "n_closed": tot, "n_day": day, "n_flt": flt,
        "n_open": n_open, "ts": time.time(),
    }
    tmp = LIVE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(live))
    os.replace(tmp, LIVE)


def fam2(stream):
    """Detailed family key: like family() but keeps aetherflow timeframes and
    the liquiditysweep A/B arms separate (used by the scorecard)."""
    s = stream
    for suf in ("-EA-T", "-EA", "-T"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s


# Walk-forward JSON written by: backtest_walkforward.py --json
# (11 windows x 14d, per-family DEPLOYED trail; keys = detailed families)
WF_JSON_PATH = os.path.join(LOG, "wf_scorecard.json")

# families too young for walk-forward -- best available evidence
FAM_EDGE_EXTRA = {
    "fixfade": {"total": 140.15, "n": 46, "pf": "6.17", "pos_pct": 76,
                 "src": "90d backtest"},
    "vwaprev": {"total": 95.17, "n": 86, "pf": "1.21", "pos_pct": 58,
                 "src": "90d backtest"},
    "dayopen": {"total": 796.05, "n": 190, "pf": "1.40", "pos_pct": 46,
                "src": "180d backtest (weekday +$788)"},
    "smvp": {"total": 1694.00, "n": 13, "pf": "3.17", "pos_pct": 69,
              "src": "live trips"},
    "aetherflow-M30": {"total": 191.02, "n": None, "pf": None, "pos_pct": None,
                        "src": "30d sweep (UT)"},
    "aetherflow-H4": {"total": 212.17, "n": None, "pf": None, "pos_pct": None,
                       "src": "60d sweep (UT)"},
    "aetherflow": {"total": None, "n": 0, "pf": None, "pos_pct": None,
                    "src": "no closed trips yet"},
    "liquiditysweep": {"total": 17.23, "n": 6, "pf": None, "pos_pct": None,
                        "src": "60d fixed (90d +$433 = deploy basis; but 0 "
                               "signals in the last 30d -- thin recent edge; "
                               "+$88.80 retired 2026-10-02, not reproducible)"},
    "liquiditysweep-BIN": {"total": None, "n": 0, "pf": None, "pos_pct": None,
                           "src": "binary A/B - unknown until it trades"},
}

# retired families that still appear in wf_scorecard.json -- not scored
WF_RETIRED = {"trendpullback", "supres"}


def load_wf():
    try:
        with open(WF_JSON_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: v for k, v in raw.items() if k not in WF_RETIRED}
    except (OSError, ValueError):
        return {}


def verdict_chip(wf, live_net):
    """(label, css-class) from walk-forward stats + live performance."""
    if wf is None:
        return ("young", "b-fresh")
    if wf.get("total", 0) < 0:
        return ("bleeding", "b-neg")
    if wf.get("decay", 0) <= -100:
        return ("decaying", "b-warn")
    if live_net < 0:
        return ("watch", "b-warn")
    return ("healthy", "b-open")


def esc(x):
    return html.escape(str(x))


def norm_positions(positions):
    """Accept raw mt5 position namedtuples and convert to plain dicts."""
    out = []
    for p in positions or []:
        out.append(dict(ticket=p.ticket, magic=p.magic, symbol=p.symbol,
                        side="BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                        vol=p.volume, open_price=p.price_open, price=p.price_current,
                        pnl=p.profit, sl=p.sl, tp=p.tp))
    return out


def render(positions=None, bal=None, eq=None):
    positions = norm_positions(positions)
    trips, today_net = load_deals()
    bal_csv, eq_csv, eq_ts = load_equity()
    if bal is None:
        bal = bal_csv
    if eq is None:
        eq = eq_csv
    pos_by_magic = defaultdict(list)
    for p in positions:
        pos_by_magic[p["magic"]].append(p)
    pos_by_stream = {}
    for st in STREAMS:
        pos_by_stream[st] = pos_by_magic.get(int(MAGIC_HINT[st]), [])
    now = datetime.now(timezone.utc)
    day_total = sum(today_net.values())
    total_closed = sum(t["net"] for t in trips.values())
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    fam_agg = defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0, "open": 0, "float": 0.0})
    for st in sorted(STREAMS, key=lambda s: (STREAMS[s][0], s)):
        chart, ea_name, style = STREAMS[st]
        t = trips.get(st, {"n": 0, "net": 0.0, "wins": 0, "last": None})
        ps = pos_by_stream.get(st, [])
        fl = sum(p["pnl"] for p in ps)
        magic = MAGIC_HINT[st]
        last_txt = "-"
        if t["last"]:
            age = (now - t["last"]).total_seconds()
            last_txt = "%dd%dh" % (age // 86400, (age % 86400) // 3600) if age > 86400 \
                else "%dh%dm" % (age // 3600, (age % 3600) // 60)
        net_cls = "pos" if t["net"] > 0 else ("neg" if t["net"] < 0 else "")
        fl_cls = "pos" if fl > 0 else ("neg" if fl < 0 else "")
        state = "OPEN" if ps else ("IDLE" if t["n"] else "FRESH")
        badge = {"OPEN": "b-open", "IDLE": "b-idle", "FRESH": "b-fresh"}[state]
        rows.append(
            f"<tr><td>{chart}</td><td><span class='mono'>{esc(st)}</span></td>"
            f"<td class='mono'>{magic}</td><td>{esc(ea_name)}</td>"
            f"<td><span class='b {badge}'>{state}</span></td>"
            f"<td>{style}</td><td class='r {net_cls}'>{t['net']:+.2f}</td>"
            f"<td class='r'>{t['n']}</td><td class='r'>{100*t['wins']/max(1,t['n']):.0f}%</td>"
            f"<td class='r {fl_cls}'>{fl:+.2f}</td>"
            f"<td class='mono'>{last_txt}</td></tr>")
        f_ = family(st)
        fa = fam_agg[f_]
        fa["n"] += t["n"]
        fa["net"] += t["net"]
        fa["wins"] += t["wins"]
        fa["open"] += len(ps)
        fa["float"] += fl

    fam_rows = []
    for f_, a in sorted(fam_agg.items(), key=lambda kv: -kv[1]["net"]):
        net_cls = "pos" if a["net"] > 0 else ("neg" if a["net"] < 0 else "")
        fl_cls = "pos" if a["float"] > 0 else ("neg" if a["float"] < 0 else "")
        fam_rows.append(
            f"<tr><td>{esc(f_)}</td><td class='r {net_cls}'>{a['net']:+.2f}</td>"
            f"<td class='r'>{a['n']}</td><td class='r'>{100*a['wins']/max(1,a['n']):.0f}%</td>"
            f"<td class='r'>{a['open']}</td><td class='r {fl_cls}'>{a['float']:+.2f}</td></tr>")

    # ---- strategy-family scorecard (walk-forward edge + live P&L) ----------
    wf = load_wf()
    detailed = defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0, "open": 0,
                                    "float": 0.0, "today": 0.0})
    for st in STREAMS:
        d = detailed[fam2(st)]
        t = trips.get(st, {"n": 0, "net": 0.0, "wins": 0})
        d["n"] += t["n"]
        d["net"] += t["net"]
        d["wins"] += t["wins"]
        d["today"] += today_net.get(st, 0.0)
        ps = pos_by_stream.get(st, [])
        d["open"] += len(ps)
        d["float"] += sum(p["pnl"] for p in ps)
    score_rows = []
    for f_, d in sorted(detailed.items(), key=lambda kv: -kv[1]["net"]):
        w = wf.get(f_) or FAM_EDGE_EXTRA.get(f_)
        src = wf.get(f_, {}).get("src") or (FAM_EDGE_EXTRA.get(f_) or {}).get("src",
                                               "walk-forward 11x14d")
        cells = []
        if w:
            if w.get("total") is not None:
                cells.append("%+.0f" % w["total"])
            if w.get("pf"):
                cells.append("PF %s" % w["pf"])
            if w.get("pos_pct") is not None:
                cells.append("%d%%w" % w["pos_pct"])
        edge_txt = " · ".join(cells) if cells else "--"
        tot = w.get("total") if w else None
        edge_cls = "pos" if (tot or 0) > 0 else \
            ("neg" if (tot is not None and tot < 0) else "")
        today_cls = "pos" if d["today"] > 0 else ("neg" if d["today"] < 0 else "")
        net_cls = "pos" if d["net"] > 0 else ("neg" if d["net"] < 0 else "")
        fl_cls = "pos" if d["float"] > 0 else ("neg" if d["float"] < 0 else "")
        chip, chip_cls = verdict_chip(wf.get(f_), d["net"])
        score_rows.append(
            f"<tr><td><b>{esc(f_)}</b></td>"
            f"<td><span class='b {chip_cls}'>{chip}</span></td>"
            f"<td class='r {edge_cls}'>{esc(edge_txt)}</td>"
            f"<td class='mono'>{esc(src)}</td>"
            f"<td class='r {net_cls}'>{d['net']:+.2f}</td>"
            f"<td class='r'>{d['n']}</td>"
            f"<td class='r'>{100*d['wins']/max(1,d['n']):.0f}%</td>"
            f"<td class='r {today_cls}'>{d['today']:+.2f}</td>"
            f"<td class='r'>{d['open']}</td>"
            f"<td class='r {fl_cls}'>{d['float']:+.2f}</td></tr>")

    pos_rows = []
    for p in sorted(positions, key=lambda x: x["pnl"]):
        pnl_cls = "pos" if p["pnl"] > 0 else ("neg" if p["pnl"] < 0 else "")
        st = None
        for s, m in MAGIC_HINT.items():
            if int(m) == p["magic"]:
                st = s
                break
        st = st or ("magic_" + str(p["magic"]))
        pos_rows.append(
            f"<tr><td class='mono'>{esc(st)}</td><td>{p['side']}</td>"
            f"<td class='r'>{p['vol']:.2f}</td><td class='r mono'>{p['open_price']:.2f}</td>"
            f"<td class='r mono'>{p['price']:.2f}</td><td class='r {pnl_cls}'>{p['pnl']:+.2f}</td>"
            f"<td class='mono'>{p['sl']:.2f}</td><td class='mono'>{p['tp']:.2f}</td></tr>")



    flt_total = sum(p["pnl"] for p in positions)
    live = {
        "gen": gen, "bal": "%.2f" % bal, "eq": "%.2f" % eq,
        "closed": "%+.2f" % total_closed, "day": "%+.2f" % day_total,
        "open": str(len(positions)), "flt": "%+.2f" % flt_total,
        "n_closed": total_closed, "n_day": day_total, "n_flt": flt_total,
        "n_open": len(positions), "ts": time.time(),
    }
    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FTTest Dashboard</title>
<script>
function clsFor(v){{return v>0?'v pos':(v<0?'v neg':'v');}}
function fmt2(x){{return (x>=0?'+':'')+x.toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}});}}
function poll(){{
 fetch('live.json',{{cache:'no-store'}}).then(function(r){{if(!r.ok)throw 0;return r.json();}}).then(function(j){{
  var set=function(id,t){{var e=document.getElementById(id);if(e)e.textContent=t;}};
  set('bal',Number(j.bal).toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}}));
  set('eqv',Number(j.eq).toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}}));
  set('closed',fmt2(j.n_closed)); set('day',fmt2(j.n_day));
  set('openp',j.n_open); set('flt',fmt2(j.n_flt));
  var c=function(id,v){{var e=document.getElementById(id);if(e)e.className=clsFor(v);}};
  c('closed',j.n_closed); c('day',j.n_day); c('flt',j.n_flt);
  set('gen','live update '+new Date(j.ts*1000).toISOString().replace('T',' ').slice(0,16)+' UTC');
  var b=document.getElementById('agebar');if(b)b.style.background='#3fb950';
 }}).catch(function(){{
  if(location.protocol.indexOf('http')===0){{var b=document.getElementById('agebar');if(b)b.style.background='#f85149';}}
 }});
}}
function loadTape(){{
 fetch('feed.jsonl',{{cache:'no-store'}}).then(function(r){{if(!r.ok)throw 0;return r.text();}}).then(function(t){{
  var lines=t.trim().split('\n').slice(-25).reverse(); var tb=document.getElementById('tape');
  if(!tb)return; tb.innerHTML='';
  for(var i=0;i<lines.length;i++){{ if(!lines[i])continue; var e=JSON.parse(lines[i]);
   var tr=document.createElement('tr'); var cls=e.entry=='in'?'':'r';
   var pnl=e.entry=='out'?' class="'+(e.pnl>=0?'pos':'neg')+'"':'';
   var when=new Date(e.ts*1000).toISOString().replace('T',' ').slice(11,16)+'Z';
   tr.innerHTML='<td class="mono">'+when+'</td><td>'+(e.entry=='in'?'OPEN':'CLOSE')+'</td>'+
    '<td class="mono">'+e.st+'</td><td>'+e.type.toUpperCase()+' '+e.vol.toFixed(2)+'</td>'+
    '<td class="r mono">'+e.price.toFixed(2)+'</td><td class="r'+pnl.replace(' class="',' ').replace(/"/g,'')+'">'+
    (e.entry=='out'? (e.pnl>=0?'+':'')+e.pnl.toFixed(2) : '--')+'</td>';
   tb.appendChild(tr);
  }}
  var b=document.getElementById('tapebar');if(b)b.style.background='#3fb950';
 }}).catch(function(){{var b=document.getElementById('tapebar');if(b)b.style.background='#f85149';}});
}}
setInterval(loadTape,30000); window.addEventListener('load',function(){{poll();loadTape();}});
</script>
<style>
body{{background:#0d1117;color:#c9d1d9;font:13px/1.45 'Segoe UI',Arial,sans-serif;margin:0;padding:18px}}
h1{{font-size:19px;margin:0 0 2px;color:#e6edf3}}
h2{{font-size:14px;margin:22px 0 8px;color:#8b949e;text-transform:uppercase;letter-spacing:.06em}}
.sub{{color:#8b949e;font-size:12px;margin-bottom:14px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 16px;min-width:130px}}
.card .k{{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
.card .v{{font-size:20px;font-weight:600;color:#e6edf3}}
.pos{{color:#3fb950}} .neg{{color:#f85149}}
table{{border-collapse:collapse;width:100%;margin-bottom:8px}}
th{{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.04em;text-align:left;
   border-bottom:1px solid #30363d;padding:5px 8px}}
td{{border-bottom:1px solid #21262d;padding:5px 8px}}
tr:hover td{{background:#161b22}}
.r{{text-align:right}} .mono{{font-family:Consolas,monospace;font-size:12px}}
.b{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600}}
.b-open{{background:#1a3a2a;color:#3fb950}} .b-idle{{background:#2a2a1a;color:#d29922}}
.b-fresh{{background:#1f2630;color:#8b949e}} .b-warn{{background:#3a2a1a;color:#f0883e}}
.b-neg{{background:#3a1a1e;color:#f85149}}
.note{{color:#8b949e;font-size:11px;margin-top:14px}}
</style></head><body>
<h1>FTTest Rig — XAUUSD · account 26122844 (demo)</h1>
<div class="sub" id="gen">generated {esc(gen)} · deals.csv session 2026-09-28→ · MT5 data dir D0E8…075</div>
<div id="agebar" style="height:3px;border-radius:2px;background:#3fb950;margin:0 0 12px"></div>
<div class="cards">
 <div class="card"><div class="k">Balance</div><div class="v" id="bal">{bal:,.2f}</div></div>
 <div class="card"><div class="k">Equity</div><div class="v" id="eqv">{eq:,.2f}</div></div>
 <div class="card"><div class="k">Session net (closed)</div><div class="v {'pos' if total_closed>=0 else 'neg'}" id="closed">{total_closed:+,.2f}</div></div>
 <div class="card"><div class="k">Today (UTC)</div><div class="v {'pos' if day_total>=0 else 'neg'}" id="day">{day_total:+,.2f}</div></div>
 <div class="card"><div class="k">Open positions</div><div class="v" id="openp">{len(positions)}</div></div>
 <div class="card"><div class="k">Floating</div><div class="v {'pos' if flt_total>=0 else 'neg'}" id="flt">{flt_total:+,.2f}</div></div>
</div>

<h2>Strategy-family scorecard — ranked by live P&amp;L (walk-forward edge + live results)</h2>
<table><tr><th>family</th><th>verdict</th><th class="r">edge: total · PF · win</th><th>evidence</th>
<th class="r">live net</th><th class="r">trips</th><th class="r">win%</th><th class="r">today</th><th class="r">open</th><th class="r">floating</th></tr>
{''.join(score_rows)}</table>
<div class="note">verdict: healthy = positive walk-forward edge &amp; positive live · watch = edge ok but live negative ·
decaying = recent windows &gt;$100 weaker than early ones · bleeding = negative edge · young = not enough history, judged on
backtest/live evidence. Edge source: walk-forward 11 windows &times; 14d at deployed trail configs where available,
else 90d/60d backtest or live-trip record (smvp, A/B binary). Refresh wf_scorecard.json by rerunning
backtest_walkforward.py --json.</div>

<h2>Per-family session P&amp;L (closed trips since 2026-09-28)</h2>
<table><tr><th>family</th><th class="r">net</th><th class="r">trips</th><th class="r">win%</th><th class="r">open</th><th class="r">floating</th></tr>
{''.join(fam_rows)}</table>

<h2>EA roster — status, magic, P&amp;L per stream</h2>
<table><tr><th>#</th><th>stream</th><th>magic</th><th>EA build</th><th>state</th><th>exit</th>
<th class="r">net closed</th><th class="r">trips</th><th class="r">win%</th><th class="r">floating</th><th>last close</th></tr>
{''.join(rows)}</table>

<h2>Live trade tape (last 25 events · refreshes every 30s)</h2>
<div id="tapebar" style="height:3px;border-radius:2px;background:#3fb950;margin:0 0 8px"></div>
<table><thead><tr><th>time</th><th>event</th><th>stream</th><th>action</th><th class="r">price</th><th class="r">pnl</th></tr></thead>
<tbody id="tape"><tr><td colspan="6">loading…</td></tr></tbody></table>

<h2>Open positions (live from MT5)</h2>
<table><tr><th>stream</th><th>side</th><th class="r">lots</th><th class="r">entry</th><th class="r">now</th>
<th class="r">P&amp;L</th><th>SL</th><th>TP</th></tr>
{''.join(pos_rows) if pos_rows else '<tr><td colspan="8">no open positions</td></tr>'}</table>

<div class="note">Rendered by C:\\FTTest\\scripts\\make_dashboard.py · refreshed every 5 min by scheduled task FTDashboard ·
all trading is done by MT5 EAs; this page is read-only. times UTC · floating = live MT5, closed P&amp;L = deals.csv</div>
</body></html>"""
    # atomic writes so the web server never serves a half-written page
    for target, data in ((OUT, page), (LIVE, json.dumps(live))):
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, target)
    print("dashboard written: %s + live.json (%d streams, %d positions, gen %s)"
          % (OUT, len(STREAMS), len(positions), gen))


if __name__ == "__main__":
    if not mt5.initialize():
        print("standalone mode: mt5 attach failed (%s) -- rendering CSV-only"
              % (mt5.last_error(),))
        positions, acc = [], None
    else:
        positions = mt5.positions_get() or []
        acc = mt5.account_info()
        mt5.shutdown()
    render(positions=positions,
           bal=acc.balance if acc else None,
           eq=acc.equity if acc else None)
