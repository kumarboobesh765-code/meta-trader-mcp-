"""Replay backtest: single-side grid v2 logic on XAUUSD M15, RR sweep.
Mirrors GridRecoveryEA v2.00: base 0.01, mult 2.0, step $1.20, TP $1.80,
max 6 layers, SL/TP synced to basket bucket, batch escape, SL-first on
ambiguous bars (conservative). $0.20 spread cost per 0.01 per layer.
"""
import csv
from datetime import datetime, timezone

STEP = 1.20
TPD = 1.80
BASE = 0.01
MULT = 2.0
MAXLAY = 6
SPREAD = 0.20  # $ per 0.01 layer entry


def load(path):
    rows = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append((int(row["time"]), float(row["open"]), float(row["high"]),
                         float(row["low"]), float(row["close"])))
    return rows


m15 = load("logs/_tmp_XAUUSD_M15.csv")
h1 = load("logs/_tmp_XAUUSD_H1.csv")
print("M15 bars=%d %s -> %s" % (len(m15),
      datetime.fromtimestamp(m15[0][0], timezone.utc).date(),
      datetime.fromtimestamp(m15[-1][0], timezone.utc).date()))

# H1 EMA200 series
K = 2 / (200 + 1)
ema = []
prev = None
for _, o, h, l, c in h1:
    prev = c if prev is None else c * K + prev * (1 - K)
    ema.append(prev)
HT = [t for t, *_ in h1]


def ema_at(ts):
    import bisect
    i = bisect.bisect_right(HT, ts) - 1
    return ema[max(0, i)]


def run(mode, rr):
    pos = []  # (entry, vol)
    d = 0     # +1 buy / -1 sell active side
    wins = losses = 0
    net = 0.0
    maxlay = 0
    cycles = 0
    cur_ema_side = 1
    for ts, o, h, l, c in m15:
        if mode == "auto":
            e = ema_at(ts)
            cur_ema_side = 1 if c >= e else -1
        side = {"long": 1, "short": -1, "auto": cur_ema_side}[mode]
        if not pos:
            if mode == "auto":
                d = side
            else:
                d = side
            px = c - (SPREAD if d == 1 else 0) + (0 if d == 1 else SPREAD)
            # buy pays spread (enter lower), sell enters higher; simplify:
            px = c - SPREAD * d * 0 + (-SPREAD / 2 * 0)
            px = c
            pos = [(px, BASE)]
            net -= SPREAD * (BASE / 0.01)
            cycles += 1
            continue
        if mode == "auto" and side != d:
            # WaitFlat: hold, manage old side only (no new layers)
            allow = False
        else:
            allow = True
        n = len(pos)
        maxlay = max(maxlay, n)
        be = sum(p * v for p, v in pos) / sum(v for _, v in pos)
        risk = TPD / rr
        if d == 1:
            sl, tp = be - risk, be + TPD
            slHit, tpHit = (l <= sl), (h >= tp)
        else:
            sl, tp = be + risk, be - TPD
            slHit, tpHit = (h >= sl), (l <= tp)
        if slHit or tpHit:
            exitPx = sl if slHit else tp  # SL-first on ambiguity
            pnl = sum(d * (exitPx - p) * v * 100 for p, v in pos)
            net += pnl
            if (pnl > 0):
                wins += 1
            else:
                losses += 1
            pos = []
            continue
        if allow and n < MAXLAY:
            adv = min(p for p, _ in pos) if d == 1 else max(p for p, _ in pos)
            trig = (c <= adv - STEP) if d == 1 else (c >= adv + STEP)
            if trig:
                nv = round(BASE * (MULT ** n), 2)
                pos.append((c, nv))
                net -= SPREAD * (nv / 0.01)
    # close leftovers at last close
    if pos:
        last = m15[-1][4]
        pnl = sum(d * (last - p) * v * 100 for p, v in pos)
        net += pnl
    tot = wins + losses
    pf_den = sum(1 for _ in [])  # placeholder
    return {"mode": mode, "rr": rr, "cycles": cycles, "W": wins, "L": losses,
            "net": net, "maxlay": maxlay,
            "win%": (100 * wins / tot) if tot else 0}


print(f"{'mode':<6}{'RR':>5}{'cycles':>8}{'W':>6}{'L':>6}{'win%':>6}{'net$':>11}{'maxlay':>7}")
results = []
for mode in ("long", "short", "auto"):
    for rr in (1.0, 1.5, 2.0, 3.0):
        s = run(mode, rr)
        results.append(s)
        print("%(mode)-6s%(rr)5.1f%(cycles)8d%(W)6d%(L)6d%(win%)6.0f%(net)11.2f%(maxlay)7d" % s)
best = max(results, key=lambda s: s["net"])
print("BEST:", best)
