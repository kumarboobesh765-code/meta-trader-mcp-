# AGENTS.md — working contract for any agent touching this repo

This repo is a MetaTrader 5 forward-testing workspace with a live VPS. Any agent
(here or on any cloned machine) MUST follow this contract so the GitHub copy always
carries the latest state and memory.

## 1. Session memory maintenance (mandatory, every working session)
- **Before starting work:** read `SESSION_STATE.md` (live state + what to check next)
  and `CHATS_HISTORY.md` (condensed memory of all past sessions). These files ARE the
  shared memory across machines — never skip them.
- **At the end of every working session (mandatory, no exceptions):**
  1. Update `SESSION_STATE.md`: current account balance/equity, open positions per EA,
     EA versions/settings table, status changes, and refresh the "What to check next"
     list. Keep the EVENING_SNAPSHOT markers intact — the nightly job rewrites only
     the block between them.
  2. Append to `CHATS_HISTORY.md`: a condensed entry of what was asked, decided,
     built, verified, and what failed — like the existing entries. Facts and numbers
     over prose. Newest entry at the end.
  3. Commit and push both files before ending the session:
     `git add SESSION_STATE.md CHATS_HISTORY.md && git commit -m "session handoff <date>" && git push origin main`
- If the session was trivial/inspection-only, still update SESSION_STATE.md and add a
  one-line CHATS_HISTORY.md entry. Memory gaps are the failure mode this contract
  exists to prevent (this rule was added after a handoff restart erased context).

## 2. Secrets — never commit
- `.env.vps`, any `.env*` file except the examples, SSH private keys, log dirs are
  gitignored on purpose. Never `git add` them, never print their values in chat.
- Telegram tokens live only in DPAPI-protected files on the VPS.

## 3. Live-money changes
- Lot sizing, layer caps, stops, equity stops are live-money decisions. Surface the
  change and its risk before editing EA defaults; the user granted wide latitude
  ("change whatever u want") but still expects a heads-up on what changed and why.

## 4. Verification discipline
- Never claim "working" without evidence: compile result on the VPS (0 errors), live
  log lines from the terminal, or a script's actual output. A curl/build exit code is
  not proof of trading behavior.
- Win rate alone is meaningless: compare avg win vs avg loss and the break-even win
  rate (`win_loss_breakdown.py` on the VPS).

## 5. VPS operations quick reference
- SSH: `ssh -i ~/.ssh/id_ed25519_vps -o BatchMode=yes $(USER)@$(HOST)` (values in `.env.vps`).
- Compile EA: upload `.mq5` then run the matching `C:\FTTest\compile_*.bat`.
- Restart MT5 (SSH-safe): `powershell -File C:\FTTest\mt_relaunch.ps1`.
- Chart files are UTF-16: writing them as UTF-8 makes MT5 silently skip them.
- Read-only reports: `python C:\FTTest\perf_summary.py`, `win_loss_breakdown.py`.

## 6. Nightly automation (already registered on the normal work PC)
- Windows task `MetaTraderRepoAutoPush`, daily 20:00: runs `scripts/evening_snapshot.py`
  (read-only VPS pull -> refreshes the EVENING_SNAPSHOT block in SESSION_STATE.md),
  then commits and pushes everything to `origin/main`.
- On any OTHER machine, recreate the task:
  `schtasks /Create /TN MetaTraderRepoAutoPush /TR "<repo>\scripts\auto_push.bat" /SC DAILY /ST 20:00 /F`
  (run from the repo root; needs git credentials + the two missing secret files:
  `.env.vps` and `~/.ssh/id_ed25519_vps`, copied securely from a machine that has them).
