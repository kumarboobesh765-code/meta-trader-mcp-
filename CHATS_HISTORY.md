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

### 2026-10-19 — user asked "SlipstreamAlt TP not working, there is no TP on the position"
- Verified: the missing T/P field is BY DESIGN — SlipstreamAlt attaches no server-side T/P;
  the basket TP = breakeven + $1.80 is computed live and closed manually as a batch
  (tagged `[tp <price>]`). Today's log shows many working escapes, e.g. `[tp 4185.07]`,
  `[tp 4179.09]`, `[tp 4170.38]`, with correct BUY→SELL alternation after each close.
- All four EAs confirmed running today: gridrecovery 571 log lines, gridbestrr 249,
  slipstream-clone 54, slipstream-alt dozens of cycles/escapes.
- Found: a 58-second burst of `open failed err=4756` (150 attempts) on 930031 at the
  03:30 pause-lift moment Monday — orders fired before the broker session had quotes.
  Rep龟 handled by the retry flag; first order landed right after. Harmless but noisy;
  could be throttled in a future version.
- Refreshed perf_summary at ~16:40 IST: balance $96,627.58, equity $96,634.60;
  930031 still +$373.67 (91 closed), others unchanged since the morning pull.

### 2026-10-19 late — SlipstreamAltEA v1.01: basket TP shown in the chart Comment
- User asked to see the escape level on the chart. Implementation: RunBasket() now records
  `g_lastBasketTP / g_lastBasketN / g_lastBasketDir` every tick; the Comment shows e.g.
  `slipstream-alt 930031  L/S = 1/2  SELL-basket TP=4166.70`. Batch-close escape behavior
  itself is UNCHANGED — display only. Version string bumped to v1.01 for positive log ID.
- Deployed: scp to C:\FTTest, copy into the Terminal Experts dir, compile via
  compile_slipstreamalt.bat → **Result: 0 errors, 0 warnings** (both compiles).
- Terminal restarted (taskkill + mt_relaunch.ps1, PID 5184 → 2328). Log confirms all four
  EAs reloaded at 16:33:31 with correct versions (930031 v1.01 first line verified).
- Reasoning note: basket-TP display only appears while a basket is live; flat state shows
  `flat, waiting cycle`. Restart did NOT touch server-side positions (2 SELLs survived,
  matched tickets before/after via Python probe).
- Account after restart: balance $96,661.67, equity $96,660.44. 930031 at +$390.36 over
  96 closed trades, still the only net-positive EA.
- Limitation flagged in handoff: Comment() text does not reach the MQL5 log, so CD-level
  proof of what's RENDERED on the chart needs one RDP eyeball — the log only proves v1.01
  is loaded and init succeeded.

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

### 2026-10-20 Tue — chart-04 Comment screenshot attempt: pipeline fixed, visual proof parked (user's call)
- User asked for a SCREENSHOT of the chart-04 Comment line (basket TP) plus confirmation that the
  updated EA (v1.01) is running in MT5.
- Found the root cause of earlier white/blank captures: the Administrator console session was
  DISCONNECTED (auto-logoff state). Fixed live with `tscon 1 /dest:console` over SSH → session
  Active on console. After that CaptureFromScreen works from scheduled-task PowerShell.
- Built and shipped a proper hidden task toolchain (all under C:\FTTest on the VPS, mirrored in
  repo vps/): capture_only.ps1 + click_chart.ps1 (click.txt "x y [x2 y2]") + menu_probe.ps1
  (-which N clicks Window menu entry N) + tile_probe.ps1 (Window > Tile Vertically) + hide.vbs
  wscript wrapper (scheduled-task powershell pops a visible console onto MT5 otherwise; wscript
  Run(...,0) hides it). Tasks: MTCapH, MTClickH, MTMenuProbe1-4, MTTile.
- Probe results: Window menu entries 1/2/4 all rendered the SAME view — chart01 GridRecovery's
  maximized MDI window sits on top, menu numbering ≠ tab numbering. Fixed with Tile Vertically
  (capture 37): all four XAUUSD H1 tiles visible side by side, but ~250px tiles clip the Comment
  text — unreadable at that size, needs zoom or a maximized single-tile pass, which the user
  chose to skip: "leave the screenshot and finish all others".
- EA verification DID complete (this was the second half of the same ask):
  - `SlipstreamAltEA.ex5` rebuilt 10/19 16:32:27, terminal PID 2328 (started 10/19 16:33) — v1.01
    is the loaded build.
  - Same-day MQL5 log shows v1.01 behavior: 11:55 SELL cycle layer 2, 12:02 `[tp 4128.02]` escape,
    12:02:19 new BUY cycle, 12:03 `[tp 4129.64]` escape, 12:03:02 new SELL cycle — alternation
    and escape-tagging both working.
  - New permanent probe `C:\FTTest\probe930031.py` (account balance/equity, open positions,
    today's closed net + win rate for magic 930031): Tue 12:40 → balance $97,805.34, equity
    $97,778.30, 1 open BUY 0.01 (−$0.01), today 145 closed +$485.84 @ 74% — record day for
    this EA since Fri 18:52 launch (+$486 lifetime-ish delta against Mon's +$374 snapshot).
- NOT verified: the Comment() text ON SCREEN (needs one RDP eyeball after tiling/zooming).
  Everything else about v1.01 is verified live. SESSION_STATE.md updated accordingly.

### 2026-10-20 Tue afternoon — user still couldn't SEE the TP -> v1.02 draws it as a chart line
- User: "but still i cant see tp for slipstream alt EA". Root understanding: the EA attaches NO
  server-side T/P by design (faithful to source bot), so the Positions tab T/P column is empty,
  and the v1.01 Comment text is easy to miss. Fix: DISPLAY the escape level where the user
  actually looks — on the chart.
- SlipstreamAltEA v1.02: new DrawTpLine()/RemoveTpLine() — OBJ_HLINE at the live basket escape
  level, refreshed every tick, lime for BUY baskets, red for SELL, dashed width-2, labelled
  `BUY/SELL-basket TP <price>`, deleted when flat and on deinit. Trading logic untouched
  (batch close at BE+$1.80 unchanged). Compile on VPS: 0 errors 0 warnings.
- Gotcha hit and fixed: the earlier `copy` into the Terminal Experts dir never landed (source
  still showed 1.01 / old timestamp) so the first two reloads printed v1.01. Explicit
  Copy-Item + vercheck.ps1 (source version line + mq5/ex5 timestamps) now part of the loop.
- The init Print ALSO said "v1.01" hardcoded (separate from #property) — bumped to v1.02.
- Terminal restarted: PID 4040 transitional (13:14, still old ex5) -> PID 6616 at 13:19 loaded
  v1.02 (log line `slipstream-alt 930031 v1.02 started ...` verified). 930031 positions
  survived the restarts (probe: 3 open, floating +$0.72; today still 145 closed +$485.84 @ 74%).
- Backup kept: C:\FTTest\SlipstreamAltEA.bak.mq5 (v1.01 source) before overwrite.
- Still unverified visually: the line itself on screen (any RDP peek while a basket is live
  shows it; green line above price for BUY basket, red below for SELL).
