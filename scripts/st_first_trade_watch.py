"""Supertrend first-close watchdog (magics 930014 / 940014).

Imported by forward_test.py's run_loop (same pattern as stuck_stop_watchdog):
runs inside the runner every 30s using its persistent healthy MT5 attach.
The FIRST time a supertrend trip closes, Telegram a one-shot alert containing
the trip and its realized SL/TP slippage vs the backtest assumption
(SL 2 x ATR(14, SMA-TR, H1) / TP 3 x ATR, ATR measured at entry time from the
H1 series). Later closes just append to supertrend_trips.log (no spam).

State file: C:\\FTTest\\logs\\st_first_alert.sent  (marker => alert already fired)
Trip log:   C:\\FTTest\\logs\\supertrend_trips.log (every close thereafter)
"""
import os
import time

FT = r"C:\FTTest"
LOG = os.path.join(FT, "logs")
MARKER = os.path.join(LOG, "st_first_alert.sent")
TRIPLOG = os.path.join(LOG, "supertrend_trips.log")
TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"
MAGICS = (930014, 940014)
LABEL = {930014: "supertrend", 940014: "supertrend-T"}


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


def _h1_atr_at(entry_ts):
    """ATR(14, SMA-of-TR) of the H1 series at the bar containing entry_ts
    (closed bars only), via the caller's live MT5 attach."""
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_H1, 1, 400)
    if rates is None or len(rates) < 20:
        return None
    trs = []
    for i in range(1, len(rates)):
        pc = rates[i - 1]["close"]
        trs.append((max(rates[i]["high"] - rates[i]["low"],
                        abs(rates[i]["high"] - pc),
                        abs(rates[i]["low"] - pc)), rates[i]["time"]))
    # ATR of the 14 bars ending at the entry bar
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
        outs = [d for d in deals if d.magic in MAGICS and d.entry == 1]
        if not outs:
            return lines
        outs.sort(key=lambda d: d.time)
        first = outs[0]
        if not os.path.exists(MARKER):
            # trip details: entry deal via position id
            ins = [d for d in deals if d.position_id == first.position_id
                   and d.entry == 0]
            i = ins[0] if ins else None
            pnl = first.profit + first.commission + first.swap
            hold = ((first.time - i.time) / 60.0) if i else 0
            a = _h1_atr_at(i.time) if i else None
            move = abs(first.price - i.price) if i else None
            slip = ("move $%.2f = %.2f ATR (assumed stop 2.0 ATR / tp 3.0 ATR)"
                    % (move, move / a)) if (a and move) else "ATR unavailable"
            msg = ("SUPERTREND FIRST CLOSE: %s trip #%d pnl=%+.2f | %s | "
                   "hold %.0f min | %s" % (LABEL.get(first.magic, first.magic),
                                           first.position_id, pnl,
                                           "WIN" if pnl > 0 else "LOSS",
                                           hold, slip))
            ok = _telegram(msg)
            lines.append("st first-close alert: %s" % ("sent" if ok else "SEND FAILED"))
            lines.append("  " + msg)
            with open(MARKER, "w") as f:
                f.write(str(first.ticket))
        # every close (incl. the first) lands in the trip log
        new = []
        seen = set()
        if os.path.exists(TRIPLOG):
            for ln in open(TRIPLOG, errors="replace"):
                if ln[:20].isdigit() or ln.split("|")[0].strip().isdigit():
                    seen.add(ln.split("|")[0].strip())
        for d in outs:
            key = str(d.ticket)
            if key in seen:
                continue
            pnl = d.profit + d.commission + d.swap
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(d.time))
            new.append("%s|%s|%s|pnl=%+.2f" % (d.ticket, ts,
                                               LABEL.get(d.magic, d.magic), pnl))
        if new:
            with open(TRIPLOG, "a") as f:
                f.write("\n".join(new) + "\n")
            lines.append("st trips logged: %d" % len(new))
    except Exception as e:      # never break the runner loop
        lines.append("st watchdog skipped: %r" % e)
    return lines
