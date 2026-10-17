"""Extract exact grid rules from live 33705313 capture (magic 300003 only)."""
import re
from collections import Counter, defaultdict

txt = open("logs/live_33705313_probe_20261014.txt", encoding="utf-8", errors="replace").read()
flow = txt.split("=== FULL DEAL FLOW")[1].split("=== ORDERS")[0]
evs = []
for l in flow.strip().split("\n"):
    m = re.match(r"(\S+) (\S+) #(\d+) (\S+) (buy|sell) ([\d.]+) @ ([\d.]+) "
                 r"magic=(300003) entry=(in|out|inout|out-by) pnl=([+-]?[\d.]+) cmt=(.*)", l)
    if not m:
        continue
    d, t, tick, sym, side, vol, px, magic, entry, pnl, cmt = m.groups()
    evs.append({"t": d + " " + t, "side": side, "vol": float(vol),
                "px": float(px), "entry": entry, "pnl": float(pnl), "cmt": cmt})

print("300003 events:", len(evs))

# 1) grid step: consecutive same-side INs with no same-side OUT between
for side in ("buy", "sell"):
    steps, run = [], []
    for e in evs:
        if e["side"] != side:
            continue
        if e["entry"] == "in":
            if run:
                steps.append(e["px"] - run[-1]["px"])
            run.append(e)
        else:
            run = []
    steps = sorted(steps)
    if steps:
        import statistics as S
        q = lambda p: steps[min(len(steps) - 1, int(p * len(steps)))]
        print("%s step n=%d min=%.2f p10=%.2f MED=%.2f p90=%.2f max=%.2f mean=%.2f" %
              (side, len(steps), steps[0], q(.1), q(.5), q(.9), steps[-1], S.mean(steps)))
        print("   most common rounded:", Counter(round(s, 1) for s in steps).most_common(6))

# 2) layer index -> lot size: position of each IN within its run
layvol = defaultdict(Counter)
maxrun = 0
for side in ("buy", "sell"):
    run = []
    for e in evs:
        if e["side"] != side:
            continue
        if e["entry"] == "in":
            run.append(e)
        else:
            for i, r in enumerate(run):
                layvol[i][r["vol"]] += 1
            maxrun = max(maxrun, len(run))
            run = []
print("max consecutive same-side INs (max layers):", maxrun)
for i in sorted(layvol):
    print("  layer %d: %s" % (i, dict(sorted(layvol[i].items()))))

# 3) TP offset: OUT price vs matched IN (same side+vol, most recent unmatched)
from collections import deque
openq = defaultdict(deque)
offs = []
for e in evs:
    k = (e["side"], e["vol"])
    if e["entry"] == "in":
        openq[k].append(e["px"])
    else:
        if openq[k]:
            pin = openq[k].popleft()
            offs.append((e["px"] - pin) * (1 if e["side"] == "buy" else -1))
offs = sorted(offs)
if offs:
    import statistics as S
    q = lambda p: offs[min(len(offs) - 1, int(p * len(offs)))]
    print("entry->exit n=%d MED=%.2f p10=%.2f p90=%.2f mean=%.2f neg=%d" %
          (len(offs), q(.5), q(.1), q(.9), S.mean(offs), sum(1 for o in offs if o < 0)))
    print("   most common:", Counter(round(o, 1) for o in offs).most_common(8))

# 4) new-cycle delay: gap between an OUT that flattens side and next IN
for side in ("buy", "sell"):
    from datetime import datetime as D
    fmt = "%m-%d %H:%M:%S"
    depth = 0
    lastflat = None
    gaps = []
    for e in evs:
        if e["side"] != side:
            continue
        if e["entry"] == "in":
            if depth == 0 and lastflat:
                gaps.append((D.strptime(e["t"], fmt) - D.strptime(lastflat, fmt)).total_seconds() / 60)
            depth += 1
        else:
            depth = max(0, depth - 1)
            if depth == 0:
                lastflat = e["t"]
    gaps = sorted(gaps)
    if gaps:
        print("%s reflatten->new-cycle gap min: n=%d MED=%.1f p90=%.1f max=%.1f" %
              (side, len(gaps), gaps[len(gaps)//2], gaps[int(.9*len(gaps))], gaps[-1]))

# 5) hedge overlap: share of events with both sides open (depth model)
db = ds = 0
both = tot = 0
for e in evs:
    if e["side"] == "buy" and e["entry"] == "in":
        db += 1
    elif e["side"] == "buy":
        db = max(0, db - 1)
    elif e["entry"] == "in":
        ds += 1
    else:
        ds = max(0, ds - 1)
    tot += 1
    if db > 0 and ds > 0:
        both += 1
print("events with both sides open: %d/%d = %.1f%%" % (both, tot, 100*both/tot))

# 6) orders: any SL/TP ever attached?
ordsec = txt.split("=== ORDERS")[1].split("=== OPEN")[0]
lines = [l for l in ordsec.strip().split("\n") if re.match(r"\d\d-\d\d", l)]
nsl = ntp = 0
for l in lines:
    m = re.search(r"sl=([\d.]+) tp=([\d.]+)", l)
    if m:
        if float(m.group(1)) > 0:
            nsl += 1
        if float(m.group(2)) > 0:
            ntp += 1
print("orders scanned=%d with SL>0: %d, with TP>0: %d" % (len(lines), nsl, ntp))
