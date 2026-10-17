# Overnight 3-grid watch — report due tomorrow (2026-10-15)

## What's running
- VPS task `FTGridWatch`: hourly `scripts/_overnight_watch.py`, 19:00 10-14 to
  08:00 10-15 (VPS time), then expires. READ-ONLY snapshots.
- Log: `C:/FTTest/logs/overnight_3grid_20261014.txt` (local copy on request).
- Evening baseline (18:0x 10-14): 11 open (930021x4 SELL synced SL/TP, 930022x5 BUY
  bare, 930023x2 SELL server SL/TP), bal $99,859.62, eq $99,849.69.

## Tomorrow's update = read the log + journal, per EA report:
1. Uptime: any gaps in hourly lines? Any EA init/REFUSING lines in
   `MQL5/Logs/20261014.log` + `20261015.log` (grep gridbestrr/slipstream-clone/
   gridrecovery + REFUSING + "account has been changed").
2. Per magic (930021/22/23): cycles, escapes (TP vs SL), layers maxed, net,
   floating now. Clone check: any new SELL opens since v1.01 (must be zero).
3. Health verdicts: all 3 ticking? PF so far? Kill-rule progress (x/200 deals)?
4. Cleanup: delete task if expired-alive (`schtasks /Delete /TN FTGridWatch /F`),
   keep the log as evidence.

## Watch items (known risks tonight)
- 930022 no-SL ladder to 0.08 already (+$32 float on deepest layer at baseline);
  a fast up-move layers it toward 0.16/0.32 with zero protection.
- 930021 4-layer SELL near its 6-cap; a cat-SL trip would print first SL data.
- Any VPS reboot kills terminal64 (no autologin-proof) — gap in hourly lines = tell.
