# CHATS_HISTORY.md — condensed memory of all working sessions

Purpose: this repo should stand alone. This file preserves the key facts, decisions,
failures and preferences from our conversations, so an agent on ANY cloned machine can
continue with full context. Newest at the end. Keep me updated each working session.

## Session history (condensed)

### Early September 2026 — repo purpose
- Workspace is a MetaTrader 5 forward-testing lab: python + MetaTrader5 package drives
  MT5 terminals locally and on a Windows VPS over SSH. Repo renamed area: originally
  an MCP (model-context-protocol) guarded setup — `scripts/mt5_mcp_guarded.py` still
  requires credentials from `.env`, never hardcoded.
- Setup: `.env.vps` (VPS host/user), OpenSSH key pair, `vps/` holds everything needed
  to deploy/stage EAs headlessly. RDP used exactly once for setup; everything after
  runs over SSH. MT5 relaunch uses a scheduled task (SSH sessions cannot start GUI apps
  in the console session).

### Mid-September — FTTest strategy factory
- Built `FTTestEA` + `FTTestCore.mqh`: 10+ strategies (breakout, london, macross, meanrev,
  smc, squeeze, straddle, sweepabs, swing, trend, vwaprev, donchian, orderflow, profile,
  supertrend, supres, trendpullback...) with fixed-SL vs trailing-SL twins, presets, walk
  -forward backtests, champion checks, weekly verdict refresh, Vantage server-time
  calibration task, Monday smoke tests, low-noise Telegram alerts (DPAPI-stored token).

### 2026-09-17 → 10-14 — live account 33705313 probe (the "slipstream-gridbot")
- We reverse-engineered the live bot (magic 300003, 6,8xx deals): single-side at a time,
  entry ladder every ~$3.50 adverse, lots 0.01/0.01/0.02/0.04…, EVERY basket escapes at
  breakeven + $1.80 via manual batch closes, NO stop-loss anywhere, 97.4% two-sided on
  the source, closed win rate 69-70%, net ~+$125/4wks on ~$1k. Produced
  `mql5/SlipstreamCloneEA.mq5` (single-side per user's earlier preference).

### Early October — 3-grid forward test on demo 26122844
- Deployed three grid EAs on XAUUSD H1: GridRecoveryEA (930021), SlipstreamCloneEA
  (930022, nicknamed Bare BUY grid), GridBestRREA (930023, AUTO EMA side picker).
- Results kept negative for 930021/930023 while 930022 was the only winner for weeks.
- Loss-minimization session (our analysis): cut lot doubling (InpLotMult 2.0 → 1.5),
  cap ladder depth (6 → 4) on 930021; user approved: "change whatever u want".

### 2026-10-15 — restarted MT5 to load v2.01 settings live
- Graceful close timed out → force kill → relaunch via scheduled task. Worked, but the
  cap change also changed the stop of the OPEN basket → closed at −$361.42 immediately.
  Lesson: parameter changes affect open baskets too (user accepted; it was their known
  risk). Learned to check closed-trade totals reconcile; found they lag one day.
- Win/loss shapes: 930021 needs ~68% wins to break even and had 65%; 930023 needs ~84%,
  had 72%. 930022 wins==losses ~1:1.
- Added the 30-minute high-impact USD news pause to GridRecoveryEA (v2.02) after user
  complained about news-time losses. Calendar API (`CalendarValueHistory`) works live
  on this terminal, returns ~6 events/48h window typically.

### 2026-10-16 — user asked why "one side only"
- Explained InpWaitFlatOnFlip: EA will NOT open a new cycle on the flipped side while
  the old basket is still open (anti-hedge safety). User accepted for existing EAs.

### 2026-10-16 — user sent screenshots of the SAME slipstream bot and requested a NEW EA
- User clarified the real rule: "not single direction — it takes a BUY cycle, then SELL,
  alternating, layer every $4". Locked in with questions answered:
    - strict alternation BUY→SELL→BUY…
    - layer lots 0.01, 0.01, 0.02, 0.04… (source-measured ladder)
    - basket TP = breakeven + $1.80 (source-measured)
    - include all safety rails (12-layer cap, $5,000 equity stop, ±30min news pause)
- Built `mql5/SlipstreamAltEA.mq5` (930031), direction parity read from its own deal
  history so restarts cannot desync the flip. Deployed to VPS chart04 (UTF-16 chart
  file — a UTF-8 write is silently skipped by MT5, this cost one restart). Confirmed:
  started 18:52, calendar found 1 high-impact USD event, first cycle BUY 0.01.

### 2026-10-16 evening — the equity-stop event (most important recent fact)
- ~21:31 gold trended hard; 930031 was at layer 7 (0.64 lots); 21:32:49 the $5,000
  equity stop fired on ALL FOUR EAs at once (eq $96,147). All closed with [eqstop]
  tags, all paused to next server day. Account: balance = equity = $95,950.57 flat.
- Client-side deltas of the Friday evening: 930022 went from +$2,395 (18:44) to
  −$1,475 (close) — gave back ~$3,900 in one trend leg with no SL.

### 2026-10-19 Monday — performance overview after weekend equity-stop auto-lift
- All four EAs lifted from the Fri equity-stop pause at 03:30 server time Monday, as
  designed. Live pull (read-only) at ~16:05 IST: 930031 back to +$373.67 in 91 closed
  trades, still the ONLY net-positive strategy on the account. 930021/930022/930023
  still structurally negative after the weekend (avg win vs avg loss shapes unchanged).
- Fixed SESSION_STATE.md stale "flat, paused" row for the account (now reflects Mon's
  live balance/equity/open-basket state) and refreshed the verdict table with real
  win/loss shapes instead of vague "needs ~XX%" phrasing.
- Found a small gap: `win_loss_breakdown.py` on the VPS still only knows the three
  original magics — 930031 is missing from its NAMES dict. Computed its shape inline:
  91 trades since Fri close, 57W/34L, avg win +$37.81, avg loss −$52.40, largest −$252.80,
  net +$373.67 (62.6% win rate vs 58.1% break-even requirement).

### Standing user preferences (still apply)
- "change whatever u want" granted, but big live-money changes (lot sizing, caps, stops)
  get surfaced before editing.
- Plain-language, honest reporting: "working perfectly" claims without verification
  were repeatedly corrected by user — keep verifying on the live VPS before claiming.
- Never echo real credentials in chat; they live only in `.env.vps` (gitignored) and
  the DPAPI-protected Telegram token on the VPS.
- Git identity configured repo-locally: kumarboobesh765-code / noreply.github.com.

## Where the numbers live on the VPS
- perf summary: `python C:\FTTest\perf_summary.py` (per-magic closed net + win rate).
- loss breakdown: `python C:\FTTest\win_loss_breakdown.py`.
- MT5 logs: `…\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs\<yyyymmdd>.log`
  (trade-side) and `…\Terminal\…\Logs\<yyyymmdd>.log` (terminal-side).
- daily watch CSV/logs: `C:\FTTest\logs\` (gitignored locally but snapshot dirs in repo
  if ever needed).
