# FTTest Operations Runbook — XAUUSD forward-test rig

**VPS** 109.122.56.70 (`ssh -i ~/.ssh/id_ed25519_vps -o BatchMode=yes Administrator@109.122.56.70`)
**Account** 26122844 VantageMarkets-Demo · MT5 `terminal64.exe` · Python runner `forward_test.py` · 33 charts
**Alerts** → Telegram (chat 1819206234). Scripts `C:\FTTest\scripts\`, logs `C:\FTTest\logs\`. Times = VPS local.

## Scheduled tasks (live from `schtasks /query`, 2026-10-01)

| Task | Schedule | Script | Does / alerts |
|---|---|---|---|
| **FTForwardTest** | at logon | `start_fttest.bat` | Spawns the runner loop + watchdog; respawns runner ≤60s if it dies |
| **MTRelaunch** | on demand | `terminal64.exe /config:mt5_autologin.ini` | Relaunches MT5 in console session (used after every bounce) |
| **FTTrailAudit** | hourly :05 | `_diag_trail_audit.py --json` | Live trail audit → `trail_audit.json`. Alert-level findings: `SUSPICIOUS` (gain ≥ activation, SL never moved), `fixed_bad` (fixed twin SL moved) |
| **FTTrailExpect** | daily 20:00 | `_trail_expect_check.py` | Post-deploy live trips vs sweep expectations → `trail_expect.json`. Flags: `UNDERPERF` (≥4 trips, avg<0 vs positive expect), `NOTRADE` (0 trips 72h+). Telegram on flags |
| **FTTrailDrift** | Mon 06:30 | `_trail_drift_weekly.py` | Reruns full trail sweep, compares best config vs deployed → `trail_drift_weekly.txt`. Reports `DRIFT` when best beats deployed >$20 |
| **FTCheck** | Mon–Fri 12:05 | `champion_check.py` | Per-open-position twin conformance (trail champ must have moved SL; fixed champ must NOT have) |
| **FTDigest** | daily 13:30 | `daily_digest.py` | Telegram digest: account, per-EA roster, TRAIL HEALTH |
| **FTDayPerf** | daily 23:00 | `_day_perf.py` | Plain-language day report to Telegram: winners/losers per strategy with human descriptions, quiet list, bottom line. File-based (no MT5 attach) |
| **FTOverview** | Mon–Fri 00:15 | `overview_report.py --tg` | Session-to-date Telegram overview |
| **FTDashboard** | every 5 min | `make_dashboard.py` | Regenerates dashboard HTML |
| **FTDashboardWeb** | at startup | `dashboard_server.py 8090` | Serves dashboard on :8090 |
| **FTMondaySmoke** | Mon 12:20 | `monday_smoke.py` | Weekly system smoke test |
| **FTVerdict** | Sat 12:10 | `weekly_verdict_refresh.py` | Refreshes champion verdicts from weekly data |
| **FTTimeCal** | Mon 10:05 | `vantage_time_calibrate.py --apply` | Broker-time offset calibration |
| **FTTightenConfirm** | one-shot (done) | `_tighten_confirm.py` | Confirmed 9/30 tighten in journal — historical |
| **FTRetireGate2 / Exec2 / Verify2** | one-shot (done) | `_retire_r2_*.py` | Round-2 chain — voted **REJECTED** (keep) 10/1, executor never fired |
| **FTSTCheck48h** | one-shot 10/2 16:00 | `_st_check_48h.py` | Supertrend live-vs-backtest after 48h |

## Manual retirement decisions (decisions.log)
- **donchian**: KEEP for 1 week (user 10/1) — review **10/8** (WF PF 0.53, −$179 live)
- **supres-T**: KEEP both twins (user 10/1) — WF bleed acknowledged, no auto-flag

## Key deployment facts
- **Trails (per family)**: FTTest twins `0.10/0.3/0.05` · aetherflow-H4 `0.8/1.0/0.25` · aetherflow-M30 `0.2/0.5/0.10` · supertrend `0.5/0.8/0.20` · liquiditysweep `0.2/0.5/0.10` · SMVP own R-chandelier. Source of truth: `make_ea_profile.py`; audit mirror: `_diag_trail_audit.py trail_of()`
- **Sizing**: all EAs fixed 0.01 lot (SMVP switched from 0.25% risk on 10/1)
- **A/B live**: chart37 binary `LiquiditySweepH4` (magic 930016, real inputs unknown until first trade) vs chart38 port `FTTest_liquiditysweep` (930015), both H4
- **Retired**: meanrev, profile (charts removed, magics kept append-only)

## Common operations
```bash
# bounce MT5 (profile changes, new ex5)
taskkill /F /IM terminal64.exe & powershell -File C:\FTTest\mt_relaunch.ps1
# restart runner (forward_test.py changes)
cmd /c C:\FTTest\restart_runner.bat
# verify all EAs loaded (expect 33 per bounce)
journal tail: Select-String 'loaded successfully' | Measure-Object
# run trail sweep / walk-forward / drift on demand
python C:\FTTest\scripts\backtest_trail_full_sweep.py
python C:\FTTest\scripts\backtest_walkforward.py
```
**Gotchas**: remote cmd needs `2>nul` (never `2>/dev/null`); `&` chains; `$` vars need EncodedCommand; never read full MT5 journal (tail it); schtasks /SD needs mm/dd/yyyy.
