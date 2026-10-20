# SESSION_STATE.md — live handoff (update me at the end of every working session)

_Last updated: 2026-10-20 (Tuesday) by the working agent._

<!-- EVENING_SNAPSHOT:BEGIN (auto-updated daily 20:00 by scripts/evening_snapshot.py) -->

### Evening snapshot — auto-generated 2026-10-20 18:30

**Source:** live pull from the VPS by `scripts/evening_snapshot.py` (perf_summary.py + today's EA log).

```text
ACCOUNT 26122844 balance=98183.63 equity=98174.40
GridRecovery (930021)
  open trades=3  floating=-1.57
  closed trades=1996  net=-1732.27  win rate=66%
Bare BUY grid (930022)
  open trades=4  floating=-3.17
  closed trades=752  net=-100.51  win rate=72%
GridBestRR v1.01 (930023)
  open trades=2  floating=-4.51
  closed trades=334  net=-988.65  win rate=71%
SlipstreamAlt (930031)
  open trades=1  floating=+0.02
  closed trades=213  net=+758.40  win rate=68%
```

```text
5872 10/20/2026 3:17:07 PM
```

<!-- EVENING_SNAPSHOT:END -->






## What happened most recently (read this first)
- **Tue 2026-10-20 evening (UTC): full performance pull for all 4 EAs.** Account $98,213.72 / equity $98,200.70. Lifetime: 930021 −$1,732.27 (66%, needs 69.2% BE), 930022 −$71.14 (71.5%, needs 71.7% BE — nearly breakeven after a +$747.68 day), 930023 −$988.65 (71%, needs 81.3% BE), 930031 +$761.63 (67.9%, needs 60.3% BE — only true winner). Today (UTC) all four green, +$1,076.34 combined.
- **Tue 2026-10-20 ~12:40 server time: v1.01 SlipstreamAltEA (930031) verified LIVE and healthy via MT5 Python probe** (C:\FTTest\probe930031.py on the VPS): balance $97,805.34 / equity $97,778.30, 1 open (0.01 BUY, −$0.01), today 145 closes net **+$485.84 at 74% win rate** — its best single day so far. Today's log shows correct momentum: `[tp 4128.02]` escape at 12:02, new BUY cycle 12:02:19, escape `[tp 4129.64]`, new SELL cycle 12:03:02 (strict alternation working).
- **Tue 2026-10-20: console-session screenshot pipeline FIXED** (was capturing pure white because the Administrator session had auto-disconnected): `tscon 1 /dest:console` re-attaches it, then scheduled-task captures work. Working scripts shipped to VPS + repo: `vps/capture_only.ps1` (screenshot only, task MTCapH), `vps/click_chart.ps1` (read C:\FTTest\click.txt "x y [x2 y2]", task MTClickH), `vps/menu_probe.ps1 -which N` (Window menu + entry N), `vps/tile_probe.ps1` (Window > Tile Vertically — leaves all 4 charts visible at once; run once to keep it sticky). All launched hidden via `wscript.exe C:\FTTest\hide.vbs <script>` (direct schtask PowerShell leaves a console window on top of MT5).
- **Chart-04 Comment visual proof NOT obtained this session** (user said "leave the screenshot"): Window-menu entries keep activating the same underlying view (chart01's maximized MDI window covers the rest; entry clicks all rendered gridrecovery's Comment). Tile Vertically DID tile all four charts (see screenshots/vps_chart_capture_37.png), but each tile is ~250px wide and the Comment text is clipped — EyeLink readable. The EA itself is proven running by log + Python probe above; only the ON-SCREEN Comment rendering still needs one RDP eyeball (or zoom-in after next tile).
- **Monday 2026-10-19 03:30 server time: all four EAs auto-lifted from the equity-stop pause** as designed (verified in the live log). All four are trading again and holding small open baskets.
- **Friday 2026-10-16, 21:32 server time: the $5,000 equity stop fired on ALL FOUR EAs**
  (equity fell to $96,147 vs balance $101,147). Everything was closed at market and each EA
  paused until the next server day. This is the safety rail working as designed, but it
  confirmed the known failure mode of these grid/martingale strategies: a strong gold trend
  against pre-positioned baskets stacks doubling layers until the stop trips.
- The new **SlipstreamAltEA (930031)** went live Friday 18:52 and reached **layer 7 (0.64
  lots)** about 2.5 hours later before the stop closed it. Its design (no SL, doubling
  ladder, basket TP) behaves exactly like the source bot but the tail risk is identical.
- As of Saturday: account flat, no open positions, all EAs in equity-stop pause (auto-lifts
  at next server-day tick, Monday).

## Account
- **Demo account 26122844**, balance **$97,805.34**, equity **$97,778.30** (Tue 2026-10-20 ~12:40 server time, live probe).
- Symbol: XAUUSD (gold), all EAs on this one symbol. Broker demo server (Vantage-style).

## Live EAs (charts in profile FTTest, all XAUUSD H1)
| Chart | EA | Magic | Version / key settings | Status |
|---|---|---|---|---|
| chart01 | GridRecoveryEA | 930021 | v2.02: base 0.01, mult **1.5**, layers ≤ **4**, step $1.20, basket TP $1.80, catastrophic SL, news filter on | LIVE, trading today (571 log lines) |
| chart02 | SlipstreamCloneEA | 930022 | v1.01: single-side BUY, base 0.01, step $3.50, TP $1.80, layers ≤ 12, no SL | LIVE, trading today (54 log lines) |
| chart03 | GridBestRREA | 930023 | v1.01: AUTO EMA(H1,200), base 0.01, step $5.00, TP $1.80, layers ≤ 6, catSL $31 | LIVE, basket 4 layers deep (0.08 lots) at ~16:10 |
| chart04 | **SlipstreamAltEA** | **930031** | **v1.02** (Tue 10/20 13:19, PID 6616): **strict BUY→SELL alternation**, base 0.01, mult 2.0, **step $4.00**, TP $1.80, layers ≤ 12, **news pause ±30 min high-impact USD**, equity stop $5k, no SL. v1.01: basket TP in Comment. **v1.02: TP now drawn as a colored horizontal line ON CHART** (OBJ_HLINE, lime=BUY basket / red=SELL, label `BUY/SELL-basket TP <price>`, removed when flat, display only) | LIVE, 3 open (BUY basket, floating ≈ +$1), today 145 closed **+$485.84 @ 74% WR** |

SlipstreamAltEA magic 930031 is NOT yet in `vps/perf_summary.py` — add it before Monday so
its results land in the daily reports.

## Cumulative closed-trade results (as of Fri close, ~the numbers to judge)
| Magic | EA | Closed | Net | Win rate | Verdict |
|---|---|---|---|---|---|
| 930021 | GridRecovery | 1,610 | **−$1,642** | 65% | needs ~68% wins to break even (avg win $9.51 vs avg loss −$20.49), persistent loser, biggest cumulative loss on the account |
| 930022 | SlipstreamClone (Bare BUY) | 617 | **−$1,224** | 73% | avg win $9.09 vs avg loss −$32.32, needs ~78% wins, had 73%; single −$1,016 trade proves the no-SL tail is real |
| 930023 | GridBestRR | 295 | **−$973** | 72% | avg win $5.06 vs avg loss −$24.30, needs ~83% wins, had 72%; structurally unfixable at current params |
| 930031 | SlipstreamAlt | 91 | **+$374** | 63% | avg win $37.81 vs avg loss −$52.40, needs ~58.1% wins, running 62.6%; ONLY strategy in true net positive lifetime, but tail risk (no SL) is identical to source bot |

**The one-sided takeaway repeated itself a third time: these baskets bleed in a trend.
Everything on this account is a grid/martingale variant. As of Mon 2026-10-19 only 930031
(SlipstreamAlt, the alternation bot) is in true net positive lifetime; the other three
are structurally negative and the recommendation to retire 930021 stands.**

## VPS (all run over SSH; key `~/.ssh/id_ed25519_vps`, creds read from `.env.vps`)
- Host/user: read `.env.vps` (gitignored on purpose).
- MT5 terminal: `terminal64.exe` PID 5184, running since Fri 18:52, profile **FTTest**.
- Compile on VPS: `vps/compile_gridrec.bat`, `vps/compile_slipstreamalt.bat` (MetaEditor CLI,
  0 errors required before any EA change goes live).
- MT5 restart (SSH-safe, scheduled-task trick): `vps/mt_relaunch.ps1` + `vps/restart_mt5.ps1`.
- Add/repair a chart file while MT5 is **stopped**: `vps/make_alt_chart.ps1` (chart files are
  UTF-16; writing them as UTF-8 makes MT5 silently skip them — this bit us once).
- Perf summary (READ-ONLY): `python C:\FTTest\perf_summary.py` over SSH.
- EA source of truth on VPS: `…\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest\`.

## What to check next (in order)
1. **One RDP eyeball on chart04** to see the NEW v1.02 TP line: a dashed horizontal line labelled `BUY-basket TP 4166.xx` (lime, or red for SELL baskets) at the live escape level. Log + Python probe prove the EA trades; the line drawing itself is unconfirmed on screen (needs ~1 min of RDP, any basket live).
2. **Watch 930023**: escaped its 4-layer basket at 16:30 Mon for a gain, then reopened. Watch it rebuild.
3. **Retire 930021** (biggest cumulative loss, −$1.7k). v2.02's tighter cap didn't turn it positive.
4. **Add a per-basket dollar stop around −$150 on 930022** or accept the -1k tail risk profile as-is.
5. **Fix `win_loss_breakdown.py` on the VPS** to include magic 930031 in its NAMES table (currently only covers 930021/930022/930023).
6. Keep watching for another Fri-evening-style gold trend re-tripping the $5,000 equity stop; it's the only guardrail these grids have.
7. Optional polish: throttle the post-pause order burst on 930031 (150x err=4756 in 58s at the 03:30 Monday lift; self-healed but noisy in the log).
8. If screen capture ever comes back pure white again: run `tscon 1 /dest:console` over SSH — the Administrator session auto-disconnected again.

## Repository pointers for the next agent
- `RUNBOOK.md`, `vps/README.md` — deployment, scheduled tasks, SSH setup.
- `mql5/*.mq5` — all EA sources; anything edited locally must be scp'd + recompiled on the
  VPS + terminal restarted (`mt_relaunch.ps1`) to take effect.
- `.env.vps` and `~/.ssh/id_ed25519_vps` are intentionally NOT in the repo (gitignored).
  Copy them securely from a machine that has them.
- `CHATS_HISTORY.md` — condensed memory of all our working sessions, for context on
  decisions already made and why.
- Every evening at 20:00 the scheduled task `MetaTraderRepoAutoPush` runs
  `scripts/auto_push.bat`: it first pulls this account/EAs snapshot from the VPS
  (`scripts/evening_snapshot.py`, read-only), then commits and pushes everything here —
  so this repo on GitHub always carries the latest numbers and state.
