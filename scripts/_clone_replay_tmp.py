"""Replay proof v2 (corrected): clone = both sides, step 3.50, lots
0.01,0.01,0.02..x2, escape be+1.80 batch, immediate re-entry, no SL.
Live fingerprint: overlap 97.4%, step +-3.5, lone exit MED 1.80,
win% 69-70%/side (incl. ~9-16% scratches), max concurrent 12/11.
Sim has no scratch rule, so closed win% -> ~100; the match bar is
mechanics (layers form, baskets escape at bucket, both sides live).
"""
import csv

STEP, TPD, MAXLAY, SPREAD = 3.50, 1.80, 12, 0.20

rows = []
with open("logs/_tmp_XAUUSD_M15.csv") as f:
    for r in csv.DictReader(f):
        rows.append((int(r["time"]), float(r["high"]),
                     float(r["low"]), float(r["close"])))


def lot(i):
    return round(0.01 if i <= 1 else 0.01 * (2 ** (i - 1)), 2)


def run_side(sign):
    pos = []
    W = L = 0
    net = 0.0
    maxrun = 0
    cycles = 0
    lone = 0
    for ts, h, l, c in rows:
        if not pos:
            pos = [(c, lot(0))]
            net -= SPREAD
            cycles += 1
            continue
        n = len(pos)
        maxrun = max(maxrun, n)
        be = sum(p * v for p, v in pos) / sum(v for _, v in pos)
        bkt = be + TPD * sign
        hit = (h >= bkt) if sign == 1 else (l <= bkt)
        if hit:
            pnl = sum(sign * (bkt - p) * v * 100 for p, v in pos)
            net += pnl
            if pnl > 0:
                W += 1
            else:
                L += 1
            if n == 1:
                lone += 1
            pos = []
            continue
        if n < MAXLAY:
            adv = min(p for p, _ in pos) if sign == 1 else max(p for p, _ in pos)
            if (c <= adv - STEP) if sign == 1 else (c >= adv + STEP):
                pos.append((c, lot(n)))
                net -= SPREAD * (lot(n) / 0.01)
    if pos:
        last = rows[-1][3]
        net += sum(sign * (last - p) * v * 100 for p, v in pos)
    tot = W + L
    return {"cycles": cycles, "W": W, "L": L,
            "win%": round(100 * W / tot, 1) if tot else 0,
            "net": round(net, 2), "maxrun": maxrun, "lone": lone}


for name, sgn in (("BUY", 1), ("SELL", -1)):
    print(name, run_side(sgn))
print("LIVE: win% 70/69 (with scratches), maxrun 12/11, overlap 97.4%, step +-3.5, TP 1.80")
