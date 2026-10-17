# MT5 VPS deployment bundle

Everything needed to run `FTTestEA` unattended on a Windows VPS, entirely
over SSH (no RDP window ever opens after the one-time setup).

## Contents

| Path | Purpose |
| --- | --- |
| `setup_vps.ps1` | One-time setup, run INSIDE an RDP session as admin |
| `keys/id_ed25519_vps.pub` | Deploy public key (private key stays on your PC) |
| `bundle/FTTestEA.ex5` | Compiled EA |
| `bundle/FTTestEA.mq5` | EA source |
| `bundle/presets/*.set` | 10 presets: 5 strategies x fixed/trailing SL twins |

## Steps

1. **One-time (RDP window, ~5 minutes):** copy this `vps/` folder to the VPS,
   run `setup_vps.ps1` as admin. It installs OpenSSH, authorizes the deploy
   key, and optionally sets auto-logon + MT5 at startup.
2. **Back on your PC:** `cp .env.vps.example .env.vps`, fill in host/user,
   then `bash scripts/vps_deploy.sh deploy`.
3. **On the VPS (manual, last time):** start MetaTrader 5 yourself (nothing
   ever launches it automatically), log in, enable **Algo Trading**, attach
   `FTTestEA` per strategy using the `MQL5\Presets\FTTestEA_*.set` files.
4. **Disconnect RDP (click X) -- never "Sign off"**, so the session keeps
   running the EA 24/7.

After that everything is headless: `bash scripts/vps_deploy.sh status` shows
whether MT5 is up and what is deployed. Redeploy after any EA rebuild.

## Security

- The deploy key has no passphrase (it is a dedicated deploy key). The
  password is never stored anywhere; rotate it after setup if it was shared.
- Optionally disable password auth on the VPS once key login works:
  in `C:\ProgramData\ssh\sshd_config` set `PasswordAuthentication no`
  and restart the sshd service.

## Scheduled tasks on the VPS

All Telegram alerts reuse the DPAPI-encrypted bot token (`C:\VPSMonitor\telegram-token.txt`, chat 1819206234). Do NOT add new alert sources casually: alerts are deliberately low-noise.

| Task | When | What | Script |
| --- | --- | --- | --- |
| `FTForwardTest` | at logon | 24/7 loop for the Python runner (7 strats x 5 pairs) | `start_fttest.bat` |
| `VPSWatchdog` | boot + logon, hidden | Telegram ONLY on: unreachable >= 5 min (confirmed, one alert + one recovery), first FTTest-magic fill (once ever). Probes internet + real MT5 IPC every 60s | `vps/vps_watchdog.py` + `setup_vps_watchdog.ps1` |
| `FTCheck` | Mon-Fri 12:05 | champion-compliance check (trail ratchets / fixed static + order fails) | `scripts/champion_check.py` (VPS) |
| `FTVerdict` | Sat 12:10 | weekly trailing-vs-fixed verdict refresh; patches WINNER + restarts runner on flips | `scripts/weekly_verdict_refresh.py` (VPS) |
| `FTTimeCal` | Mon 10:05 | Vantage server-time calibration: measures offset from LIVE ticks, derives London hours from offset + UK DST, patches `forward_test.py` + 3 MQL5 sources, recompiles EAs, restarts runner + MT5. Skips silently when market closed; refuses drift > 3h without `--force` | `scripts/vantage_time_calibrate.py` (VPS) |
| `FTMondaySmoke` | Mon 12:20 | open smoke test: deals/equity CSVs fresh, straddle/london slots armed/filled, no 10015/10016/10027 in runner log, runner alive. One Telegram report | `scripts/monday_smoke.py` (VPS) |
| `MTRelaunch` | one-shot, recreated on demand | console-session MT5 relaunch (short 8.3 path, no inner quotes) | `mt_relaunch.ps1` |

Retired: `VPSMonitor` (chatty monitor.ps1 loop killed by `setup_vps_watchdog.ps1`; `C:\VPSMonitor\monitor.ps1` remains only as the token host), `FXTEST` (deleted). Note: `scripts/vps_watchdog.sh`/`.bat` (task `FTWatchdog`) is a DIFFERENT, older local-PC log-pull watchdog -- the VPS-side one is `vps/vps_watchdog.py`.
