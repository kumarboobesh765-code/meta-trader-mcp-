# SESSION_STATE.md — live handoff (update me at the end of every working session)

_Last updated: 2026-10-17 (Saturday, market closed) by the working agent._

<!-- EVENING_SNAPSHOT:BEGIN (auto-updated daily 20:00 by scripts/evening_snapshot.py) -->

### Evening snapshot — auto-generated 2026-10-17 18:30

**Source:** live pull from the VPS by `scripts/evening_snapshot.py` (perf_summary.py + today's EA log).

```text
ACCOUNT 26122844 balance=95950.57 equity=95950.57
GridRecovery (930021)
  open trades=0  floating=+0.00
  closed trades=1420  net=-1744.73  win rate=64%
Bare BUY grid (930022)
  open trades=0  floating=+0.00
  closed trades=530  net=-1475.32  win rate=72%
GridBestRR v1.01 (930023)
  open trades=0  floating=+0.00
  closed trades=269  net=-1026.93  win rate=71%
SlipstreamAlt (930031)
  open trades=0  floating=+0.00
  closed trades=30  net=+141.18  win rate=37%
```

```text
5184 10/16/2026 6:52:25 PM


(no EA log today - weekend or terminal down)
```

<!-- EVENING_SNAPSHOT:END -->




## What happened most recently (read this first)
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
- **Demo account 26122844**, balance **$95,950.57**, equity **$95,950.57** (flat).
- Symbol: XAUUSD (gold), all EAs on this one symbol. Broker demo server (Vantage-style).

## Live EAs (charts in profile FTTest, all XAUUSD H1)
| Chart | EA | Magic | Version / key settings | Status |
|---|---|---|---|---|
| chart01 | GridRecoveryEA | 930021 | v2.02: base 0.01, mult **1.5**, layers ≤ **4**, step $1.20, basket TP $1.80, catastrophic SL, news filter on | paused (equity stop, auto-lifts) |
| chart02 | SlipstreamCloneEA | 930022 | v1.01: single-side BUY, base 0.01, step $3.50, TP $1.80, layers ≤ 12, no SL | paused (equity stop) |
| chart03 | GridBestRREA | 930023 | v1.01: AUTO EMA(H1,200), base 0.01, step $5.00, TP $1.80, layers ≤ 6, catSL $31 | paused (equity stop) |
| chart04 | **SlipstreamAltEA** | **930031** | v1.00: **strict BUY→SELL alternation**, base 0.01, mult 2.0, **step $4.00**, TP $1.80, layers ≤ 12, **news pause ±30 min high-impact USD**, equity stop $5k, no SL | paused (equity stop) |

SlipstreamAltEA magic 930031 is NOT yet in `vps/perf_summary.py` — add it before Monday so
its results land in the daily reports.

## Cumulative closed-trade results (as of Fri close, ~the numbers to judge)
| Magic | EA | Closed | Net | Win rate | Verdict |
|---|---|---|---|---|---|
| 930021 | GridRecovery | 1,420 | **−$1,744** | 64% | needs ≥68%, still losing after v2.02 tune |
| 930022 | SlipstreamClone (Bare BUY) | 530 | **−$1,475** | 72% | was +$2,395 at 18:44 Fri, lost ~$3,900 in the Fri-evening trend — its no-SL tail fired |
| 930023 | GridBestRR | 269 | **−$1,027** | 71% | still below break-even PF after v1.01 verdict window |
| 930031 | SlipstreamAlt | new | (first cycles mostly positive before stop) | — | needs ~100 closed cycles before judging |

**The one-sided takeaway repeated itself a third time: these baskets bleed in a trend.
Everything on this account is a grid/martingale variant; none has proven it survives a
strong directional gold market.**

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
1. **Monday at market open**: confirm all four EAs auto-lifted from the equity-stop pause
   (`grep "pause lifted" <day>.log`) and that they trade on the intended settings above.
2. **Decide the fate of 930021** (biggest cumulative loss, −$1.7k). Recommendation: pause or
   retire it; v2.02's tighter cap did not turn it positive.
3. **Judge 930022's tail**: it gave back ~$3,900 in one evening with zero SL. Either accept
   that profile or add a per-basket dollar stop around −$150.
4. **Watch 930031**: verify its FIRST alternation (BUY cycle closes at basket TP or eqstop →
   next cycle must open SELL). Check at least 2 full cycles before trusting the parity logic.
5. **Do not judge any of this by win rate alone.** Use avg win vs avg loss and the
   break-even win rate (`python C:\FTTest\win_loss_breakdown.py`).
6. Weekly: run `scripts/_day_perf.py` / `scripts/overview_report.py` for the digest.

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
