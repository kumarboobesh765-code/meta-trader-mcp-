# SlipstreamCloneEA — saved for tomorrow (2026-10-15)

## What is saved and where
- Source: `mql5/SlipstreamCloneEA.mq5` (local) + `C:\FTTest\mql5\SlipstreamCloneEA.mq5` (VPS)
- Binary: `.../MQL5/Experts/FTTest/SlipstreamCloneEA.ex5` — compiled 0 errors, 0 warnings
- Evidence: `logs/live_33705313_probe_20261014.txt` (6,841 deals) + `logs/_tmp_grid300003.csv`
  (position-linked) + `scripts/_grid_extract_tmp.py` + `scripts/_clone_replay_tmp.py`
- v2.01 (930021) still on the demo chart; clone untouched by it.

## Recommended order (demo proves safety before real money)
1. Terminal back to demo 26122844 (GUI login; autologin restart did NOT switch it on 10-14).
2. Attach clone on a 2nd XAUUSD chart, magic **930022**, defaults (step 350, TP 180,
   max 12 layers, equity stop 5000).
3. Add `930022: "gridclone-EA"` to `forward_test.py` MAGICS (+ twin_split/day_perf),
   restart runner, verify both magics log.
4. Watch 1-2 weeks: clone should mirror the source fingerprint (both sides, ~70% win,
   batch `[tp]` closes). Compare vs 930021 v2.01.

## Going live (real money — read twice)
- The clone has **NO stop-loss and no server TP** (faithful to magic 300003, which
  layers to 5.12 lots). On ~$995 that is genuine blow-up risk in a fast trend.
- It **refuses REAL accounts by default** (`InpAllowReal=false`). Enabling it there
  requires a deliberate `InpAllowReal=true` + master-password session (investor
  sessions cannot trade). Suggested guardrails if you insist: keep `InpMaxLayers=12`,
  keep `InpEquityStopMoney` ON (e.g. 200 USC on a 99k-cent balance), start 0.01.
- My advice: demo A/B first. The replay already warns expectancy is fragile.

## Terminal state left on 2026-10-14 night
- VPS terminal on **live 33705313 (investor, read-only)** — do NOT run `mt_relaunch`
  or kill terminal64 without re-login plan; autologin points at demo and the live
  investor password is NOT stored anywhere here.
