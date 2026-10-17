"""Fixfade/vwaprev first-trade watchdog (magics 930009/940009, 930013/940013).

Imported by forward_test.py's run_loop (same pattern as st_first_trade_watch):
runs inside the runner every 30s using its persistent healthy MT5 attach.
Per family, the FIRST closed trip triggers a Telegram verification alert:
  - fill: entry price vs the M15 close of the signal bar (slippage proxy)
  - sizing: deal volume must be 0.01 (fixed-lot rig rule)
  - hold time vs the backtest time-stop (fixfade 8 bars = 2h; vwaprev ~1d)
  - move: |exit-entry| in ATR(14, M15) units vs backtest assumptions
Later closes append to the trip log (no spam). Every close re-checks sizing
and flags violations in the log.

State:    C:\\FTTest\\logs\\nf_first_alert_<fam>.sent
Trip log: C:\\FTTest\\logs\\newfam_trips.log   (ticket|ts|label|vol|pnl)
"""
import os
import time

FT = r"C:\FTTest"
LOG = os.path.join(FT, "logs")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
FAMILIES = {
    "fixfade": (930009, 940009, "backtest: fade pre-fix impulse >=0.5 ATR, "
                                "SL 1.5 ATR, TP 1.0x impulse, 8-bar (2h) stop"),
    "vwaprev": (930013, 940013, "backtest: fade VWAP-deviation extreme, "
                                "SL 1.5 ATR, TP toward VWAP"),
    "dayopen": (930017, 930017, "backtest: weekday server-day-open long, "
                                "SL 2.0 ATR96, no TP, 16-bar (4h) stop"),
}
TIME_STOP_H = {"fixfade": 3.0, "vwaprev": 26.0, "dayopen": 5.0}   # flag holds far beyond stop
MAGIC2FAM = {m: f for f, ms in FAMILIES.items() for m in ms}


def _telegram(text):
    import subprocess
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def _m15_atr_at(entry_ts):
    """ATR(14, SMA-of-TR) of M15 at the bar containing entry_ts (closed bars)."""
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_M15, 1, 500)
    if rates is None or len(rates) < 20:
        return None
    trs = []
    for i in range(1, len(rates)):
        pc = rates[i - 1]["close"]
        trs.append((max(rates[i]["high"] - rates[i]["low"],
                        abs(rates[i]["high"] - pc),
                        abs(rates[i]["low"] - pc)), rates[i]["time"]))
    window = [tr for tr, t in trs if t <= entry_ts]
    if len(window) < 14:
        return None
    return sum(window[-14:]) / 14.0


def check_once(name_of=lambda m: str(m)):
    """Called by the runner each loop. Returns log lines."""
    lines = []
    try:
        import MetaTrader5 as mt5
        deals = mt5.history_deals_get(time.time() - 7 * 86400,
                                      time.time() + 4 * 3600) or []
        outs = [d for d in deals if d.magic in MAGIC2FAM and d.entry == 1]
        if not outs:
            return lines
        outs.sort(key=lambda d: d.time)
        # trip log append (every close, dedup by ticket)
        triplog = os.path.join(LOG, "newfam_trips.log")
        seen = set()
        if os.path.exists(triplog):
            for ln in open(triplog, errors="replace"):
                seen.add(ln.split("|")[0].strip())
        ins_by_pos = {}
        for d in deals:
            if d.magic in MAGIC2FAM and d.entry == 0:
                ins_by_pos.setdefault(d.position_id, []).append(d)
        new = []
        for d in outs:
            if str(d.ticket) in seen:
                continue
            fam = MAGIC2FAM[d.magic]
            pnl = d.profit + d.commission + d.swap
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(d.time))
            volflag = "" if abs(d.volume - 0.01) < 1e-6 else " VOL!=0.01!"
            new.append("%s|%s|%s|vol=%.2f|pnl=%+.2f%s"
                       % (d.ticket, ts, name_of(d.magic), d.volume, pnl, volflag))
            # one-shot Telegram per family
            marker = os.path.join(LOG, "nf_first_alert_%s.sent" % fam)
            if not os.path.exists(marker):
                i = (ins_by_pos.get(d.position_id) or [None])[0]
                hold_h = ((d.time - i.time) / 3600.0) if i else 0.0
                a = _m15_atr_at(i.time) if i else None
                move = abs(d.price - i.price) if i else None
                slip = ""
                if i is not None:
                    sig_px = i.price
                    slip = ("entry %.2f | move $%.2f" % (sig_px, move))
                    if a:
                        slip += " = %.2f ATR" % (move / a)
                tstop = TIME_STOP_H.get(fam, 24.0)
                tflag = " TIME-STOP-LATE?" if hold_h > tstop else ""
                szflag = "" if abs(d.volume - 0.01) < 1e-6 else " SIZING-FLAG vol=%.2f" % d.volume
                msg = ("%s FIRST CLOSE: %s pnl=%+.2f vol=%.2f%s | hold %.1fh "
                       "(stop ~%.0fh)%s | %s | assumption: %s"
                       % (fam.upper(), name_of(d.magic), pnl, d.volume, szflag,
                          hold_h, tstop, tflag, slip, FAMILIES[fam][2]))
                ok = _telegram(msg)
                lines.append("%s first-close alert: %s"
                             % (fam, "sent" if ok else "SEND FAILED"))
                lines.append("  " + msg)
                with open(marker, "w") as f:
                    f.write(str(d.ticket))
        if new:
            with open(triplog, "a") as f:
                f.write("\n".join(new) + "\n")
            lines.append("newfam trips logged: %d" % len(new))
    except Exception as e:      # never break the runner loop
        lines.append("newfam watchdog skipped: %r" % e)
    return lines
