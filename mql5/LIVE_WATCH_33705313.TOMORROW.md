# Live watch: 33705313 slipstream-gridbot — plan for tomorrow (2026-10-15)

## Trigger
User logs the VPS terminal into live 33705313 (investor OK, read-only) in the GUI,
then says "watch". Do NOT restart the terminal afterwards — `mt_relaunch` fires the
demo autologin and kills the live session (happened 2026-10-14).

## Watch loop (30–60 min, read-only, nothing sent)
1. Snapshot loop every ~3 min: account + positions + new deals/orders since last
   poll (`scripts/_full_state_tmp.py` pattern; rewrite fresh, investor-safe).
2. Tail VPS terminal journal for any `slipstream-gridbot` / magic-300003 print
   lines — the one evidence class never captured (would confirm trigger logic
   instead of inferring it).
3. Reconstruct each completed basket live: layer spacing, lot sequence, breakeven
   bucket path, `[tp]` escape price, re-entry gap. Diff every field against the
   clone spec below.

## Clone spec to verify against (measured 2026-10-14, n in parens)
- Step $3.50 adverse past most-adverse entry (1,652 adds, MED +-3.52/3.54)
- Lots 0.01, 0.01, 0.02, 0.04 ... x2 from layer 2 (max run 13, up to 5.12)
- Escape whole side at breakeven + $1.80 (2,050 true lone exits, MED exactly 1.80)
- Immediate re-entry when flat (median gap 0.0 min), both sides (97.4% overlap)
- Zero server SL/TP ever (6,834 orders grep-proven); closes are manual `[tp X]`
- Open questions: 9–16% scratch exits near breakeven-spread (rule unidentified);
  possible session/spread filters; 46 ghost opens (1.3%, immaterial)

## Evidence on disk (do not re-pull)
- `logs/live_33705313_probe_20261014.txt` (6,841 deals/60d, 753 KB)
- `logs/_tmp_grid300003.csv` (position-linked, 6,786 rows)
- `scripts/_grid_extract_tmp.py`, `scripts/_clone_replay_tmp.py`
- Clone: `mql5/SlipstreamCloneEA.mq5` v1.01 (single-side LONG_ONLY default);
  handoff: `mql5/SlipstreamCloneEA.TOMORROW.md`

## Current demo state (left running)
- chart01: GridRecoveryEA v2.01, magic 930021 (AUTO + catastrophic SL)
- chart02: SlipstreamCloneEA v1.01, magic 930022 (LONG_ONLY, close-only SELL)
- Both logging via runner (`grid-EA`, `gridclone-EA` labels live)
