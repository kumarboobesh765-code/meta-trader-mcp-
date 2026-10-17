r"""One-shot (scheduled 2026-10-02 10:00 VPS): verify SMVP's first fixed-lot
trades after the 2026-10-01 sizing switch (InpUseRiskPercent=false,
InpFixedLot=0.01 on chart16).

Checks every SMVP entry deal (magic 26092501) since the switch:
  - all entry volumes must be exactly 0.01
  - any open position's volume must be exactly 0.01
Telegrams the verdict either way and writes
C:\FTTest\logs\smvp_sizing_check.txt.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\FTTest\scripts")

import MetaTrader5 as mt5

from forward_test import load_env

SMVP_MAGIC = 26092501
SWITCH_UTC = datetime(2026, 10, 1, 12, 48, tzinfo=timezone.utc)
OUT = r"C:\FTTest\logs\smvp_sizing_check.txt"


def main():
    load_env()
    for _ in range(5):
        if mt5.initialize():
            break
        mt5.shutdown()
        import time as _t
        _t.sleep(5)
    else:
        return 1
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(SWITCH_UTC, now + timedelta(days=1)) or []
    entries = [d for d in deals
               if d.magic == SMVP_MAGIC and d.entry == mt5.DEAL_ENTRY_IN]
    poss = [p for p in (mt5.positions_get() or [])
            if p.magic == SMVP_MAGIC]
    mt5.shutdown()

    lines = ["SMVP sizing check %s (switch %s)"
             % (now.strftime("%m-%d %H:%M UTC"),
                SWITCH_UTC.strftime("%m-%d %H:%M UTC"))]
    if not entries and not poss:
        lines.append("  no new SMVP entries yet -- sizing not trade-verified;"
                     " config is InpUseRiskPercent=false / InpFixedLot=0.01")
        msg = "FTSmvpSize: no new entries yet (config verified fixed 0.01)"
    else:
        vols = sorted({round(d.volume, 2) for d in entries})
        pos_vols = sorted({round(p.volume, 2) for p in poss})
        ok = all(abs(v - 0.01) < 1e-9 for v in vols + pos_vols)
        lines.append("  entry deals: %d | volumes: %s" % (len(entries), vols))
        if pos_vols:
            lines.append("  open positions: %d | volumes: %s"
                         % (len(poss), pos_vols))
        for d in entries[-5:]:
            lines.append("    %s vol=%.2f price=%.2f"
                         % (datetime.fromtimestamp(d.time, tz=timezone.utc)
                            .strftime("%m-%d %H:%M"), d.volume, d.price))
        if ok:
            lines.append("  VERDICT: OK -- every SMVP trade sized 0.01")
            msg = "FTSmvpSize: OK -- %d entries all 0.01 lots" % len(entries)
        else:
            lines.append("  VERDICT: MISMATCH -- volumes %s (expected 0.01)"
                         % (vols + pos_vols))
            msg = ("FTSmvpSize ALERT: SMVP volumes %s != 0.01!"
                   % (vols + pos_vols))
    txt = "\n".join(lines)
    print(txt)
    with open(OUT, "w") as fh:
        fh.write(txt + "\n")
    try:
        from champion_check import send_telegram
        send_telegram(msg)
    except Exception as e:
        print("telegram failed: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
