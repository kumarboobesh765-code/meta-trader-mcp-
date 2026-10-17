r"""Stuck-stop watchdog for the FTTest rig.

Problem it solves (seen 2026-09-29): the broker server lags (p90 order/modify
ack 60s+), price crosses a position's SL/TP and the stop does not execute for
minutes -- or at all until price reverts. This module runs inside the
forward_test runner loop (every 30s): it detects crossings that persist,
alerts Telegram and then AUTO-CLOSES the position market-side (retries
included), preserving the EA magic so stats stay attributed.

Rules (2026-09-29, two-tier design):
  - the EAs are the FIRST responder: from 30s of breach they re-send the stop
    (pulse re-trigger) and market-close at 180s (see StuckStopGuard in
    FTTestCore.mqh / AetherFlowEA.mq5 / smvp)
  - this Python watchdog is the VISIBILITY + backstop tier: it Telegram-alerts
    on the FIRST loop it sees a crossing, and only closes itself if the
    crossing survives past CLOSE_AFTER_SEC (the EA normally wins that race)
  - threshold > $0.50 beyond the stop (spread / single-tick jitter guard)
  - cooldown  > 15 min between close attempts on the same ticket
  - never raises: watchdog failures are logged and swallowed by the runner
"""
import os
import subprocess
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

TOKEN_FILE = r"C:\VPSMonitor\telegram-token.txt"
CHAT_ID = "1819206234"

THRESH = 0.50          # min distance beyond the stop, in symbol points ($ on XAU)
CLOSE_AFTER_SEC = 180  # only close if the crossing outlives the EA give-up
COOLDOWN_SEC = 900     # min gap between close attempts on the same ticket
MAX_TRIES = 3          # market-close attempts per watchdog cycle

# ticket -> {"since": first-crossing epoch, "alerted": bool, "last_act": epoch, "tries": int}
_state = {}


def send_telegram(text):
    ps = ("$t=(Get-Content '%s' -Raw).Trim();"
          "$s=ConvertTo-SecureString $t;"
          "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
          "$tok=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p);"
          "Invoke-RestMethod -Uri ('https://api.telegram.org/bot'+$tok+'/sendMessage')"
          " -Method Post -Body @{chat_id='%s';text='%s'} | Out-Null"
          % (TOKEN_FILE, CHAT_ID, text.replace("'", "")))
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    except Exception:
        pass  # alerting must never break the loop


def _crossing(p):
    """Return the stop level price has crossed beyond, or None."""
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return None
    if p.type == mt5.POSITION_TYPE_BUY:
        # SL below: breach when BID < sl; TP above: breach when BID > tp
        if p.sl and tick.bid < p.sl - THRESH:
            return p.sl
        if p.tp and tick.bid > p.tp + THRESH:
            return p.tp
    else:
        if p.sl and tick.ask > p.sl + THRESH:
            return p.sl
        if p.tp and tick.ask < p.tp - THRESH:
            return p.tp
    return None


def _close_position(p):
    """Market-close with retries; returns (ok, detail)."""
    for attempt in range(1, MAX_TRIES + 1):
        cur = mt5.positions_get(ticket=p.ticket)
        if not cur:
            return True, "closed (already gone)"
        pos = cur[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": pos.ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 300,
            "magic": pos.magic,
            "comment": "watchdog-unstick",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL,
                               mt5.TRADE_RETCODE_PLACED):
            return True, "closed @ %s (try %d)" % (req["price"], attempt)
        time.sleep(5)  # server is lagging; give it a beat before retry
    return False, "close FAILED after %d tries" % MAX_TRIES


def check_once(name_of=lambda m: str(m)):
    """One watchdog pass over all open positions. Returns log lines."""
    lines = []
    now = time.time()
    try:
        positions = mt5.positions_get() or []
    except Exception as e:
        return ["watchdog: positions_get failed: %r" % e]
    live = {p.ticket for p in positions}
    for t in [t for t in _state if t not in live]:
        del _state[t]  # position gone: stop fired late, or we closed it

    for p in positions:
        st = _state.setdefault(p.ticket, {"since": None, "alerted": False,
                                          "last_act": 0.0, "tries": 0})
        stop = _crossing(p)
        if stop is None:
            _state.pop(p.ticket, None)  # price reverted: reset (like today's 3 sells)
            continue
        if st["since"] is None:
            st["since"] = now
        held = now - st["since"]

        if not st["alerted"]:
            st["alerted"] = True
            msg = ("STUCK STOP %s  %s #%d %s pnl=%+.2f\n"
                   "price through %s (threshold $%.2f)\n"
                   "EA re-triggering; watchdog closes at %ds if still stuck"
                   % (name_of(p.magic), p.symbol, p.ticket,
                      "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                      p.profit, stop, THRESH, CLOSE_AFTER_SEC))
            send_telegram(msg)
            lines.append("watchdog: CROSSING #%d %s %s %.2f held %ds -> alert sent"
                         % (p.ticket, p.symbol, p.magic, stop, int(held)))

        if held >= CLOSE_AFTER_SEC and now - st["last_act"] >= COOLDOWN_SEC:
            st["last_act"] = now
            st["tries"] += 1
            ok, detail = _close_position(p)
            icon = "closed" if ok else "UNRESOLVED"
            msg = ("WATCHDOG %s #%d (%s): %s\npnl at action: %+.2f (try %d)"
                   % (icon, p.ticket, name_of(p.magic), detail, p.profit, st["tries"]))
            send_telegram(msg)
            lines.append("watchdog: %s #%d %s" % (icon, p.ticket, detail))
            if ok:
                _state.pop(p.ticket, None)
    return lines


def selftest():
    """No MT5: verify the telegram path only."""
    send_telegram("watchdog selftest: telegram path OK")
    print("selftest sent")


if __name__ == "__main__":
    selftest()
