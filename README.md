# MetaTrader 5 MCP for Freebuff

Trade/monitor a MetaTrader 5 account from Freebuff via the
[metatrader-mcp-server](https://github.com/ariadng/metatrader-mcp-server) MCP bridge,
with safety rails around live trading.

## Use from anywhere

```bash
git clone https://github.com/kumarboobesh765-code/meta-trader-mcp-.git
cd meta-trader-mcp-
cp .env.example .env      # then fill in your DEMO credentials
```

Requirements on any machine: **Windows** (the MetaTrader5 SDK is Windows-only),
**Python 3.10+** with `python` on PATH, `pip install metatrader-mcp-server`,
and a running MetaTrader 5 terminal. All paths in the config are relative, so
the clone location does not matter.

**Never commit `.env`** — it holds your MT5 credentials and is git-ignored.
If it ever shows up in `git status`, stop and remove it from the index.

## Files

| File | Purpose |
| --- | --- |
| `.agents/mcp.json` | Freebuff MCP registration (no secrets - just runs the guarded launcher) |
| `.agents/trader.ts` | Freebuff custom trading agent (ported Trading Assistant skill) |
| `scripts/mt5_mcp_guarded.py` | Safety wrapper: never auto-starts MT5, demo-only by default |
| `scripts/mt5_smoke_test.py` | Repeatable end-to-end verification (MCP + guard + patch) |
| `scripts/forward_test.py` | Live forward-test runner: 4 demo-only strategies on XAUUSD |
| `scripts/forward_charts.py` | Renders 4 charts + auto-refresh dashboard from the test logs |
| `mql5/FTTestEA.mq5` | Native MT5 EA: 5 strategies x fixed/trailing SL, demo-only |
| `scripts/compile_ea.bat` | Headless MetaEditor rebuild of the EA |
| `.env.example` | Credential template - copy to `.env` and fill in |

## Setup

1. `cp .env.example .env` and fill in your **demo** account `login`, `password`, `server`.
2. **Open MetaTrader 5 manually and log in.** The agent never opens MT5 for you -
   if it is closed, the launcher stops and asks you to open it.
3. In MT5: Tools -> Options -> Expert Advisors -> check **Allow algorithmic trading**.
   This checkbox is also the master kill-switch: uncheck it to instantly stop any
   automated trading.
4. Restart Freebuff **from this folder** (MCP config is only loaded at startup,
   from the launch directory).
5. Verify: `python scripts/mt5_smoke_test.py`
6. Try: "What's my account balance?" or ask the `trader` agent.

## Safety rails

- **MT5 is never launched automatically.** If the terminal is not running, startup
  fails with a message asking you to open it manually.
- **Demo/contest accounts only.** Connecting to a real-money account requires
  setting `MT5_ALLOW_LIVE=1` in `.env` deliberately; without it the server refuses to start.
- **No secrets in config or git.** Credentials live only in `.env` (git-ignored);
  the guard also fails if `.env` ever becomes tracked by git.
- **stdio only.** The launcher forces stdio transport, so no unauthenticated
  network port is ever opened with trading access.
- **The `trader` agent is tool-locked** to the 25 trading tools (no shell/file access)
  and is instructed to never bypass the guard or open MT5.

## What the agent can do

25 tools: account info, live prices, candles, symbols, market/pending orders,
position management (close one/all/profitable/losing), and trade history.
Every order tool places **real orders on the connected account** - which is why
that account should be a demo account.

## Forward testing (backtest vs live)

Backtests flatter strategies: they ignore real spread, news slippage and latency.
`scripts/forward_test.py` answers that by trading 4 simple strategies live on the
demo account (XAUUSD, 0.01 lot, SL/TP always set, max 1 position per strategy):

Each strategy trades twice from the same signal - a fixed-SL twin (magic 9100xx)
and a trailing-SL twin (magic 9200xx, `-T`, SL trails 1.2 ATR behind price once
1 ATR in profit) - so we can measure whether trailing stops really make more
profit instead of guessing.

| Magic (fixed / trailing) | Strategy | Signal |
| --- | --- | --- |
| 910001 / 920001 | `breakout` | Donchian-20 breakout on M15 (the one we backtested) |
| 910002 / 920002 | `meanrev` | RSI(14) fade on M15 |
| 910003 / 920003 | `macross` | EMA9/EMA21 cross on M30 |
| 910004 / 920004 | `straddle` | StraddleV2-style dual stop orders around the hourly range |

- Run: `python scripts/forward_test.py` (`--check` = preflight only). It is
  demo-only, never auto-launches MT5, and logs every deal with real fills to
  `logs/forward/deals.csv`.
- Charts: `python scripts/forward_charts.py` -> `charts/` (equity per strategy,
  daily P&L, drawdown, forward-vs-backtest) plus `charts/dashboard.html`.
- Stop it: `taskkill /PID <pid> /F` (open positions stay, protected by SL/TP).

## Native EA (no Python / Freebuff needed)

`mql5/FTTestEA.mq5` is a single native MT5 EA that runs all 5 forward-test
strategies (breakout, meanrev, macross, straddle, and the SMC liquidity-sweep
strategy from the video) with the same rules as `scripts/forward_test.py`.

- **Install:** already compiled into `MQL5\Experts\FTTest\` as `FTTestEA.ex5`
  (rebuild any time with `scripts\compile_ea.bat`). Restart MT5 (or right-click
  Navigator -> Refresh) to see **FTTestEA**.
- **Auto-attach profile:** `python scripts/make_ea_profile.py` generates an MT5
  profile (`vps/bundle/profile/FTTest/`) with 10 XAUUSD charts, one per
  strategy/SL twin, FTTestEA pre-attached. Deploy it to
  `MQL5\Profiles\Charts\FTTest\` and set `ProfileLast=FTTest` in
  `config\common.ini` (only while MT5 is closed) so all 10 EAs load at startup.
- **Use:** drag FTTestEA onto one chart per strategy. Set `InpStrategy`,
  `InpMagic` (9100xx = fixed SL, 9200xx = trailing twin with `InpUseTrailing=true`),
  timeframe and 0.01 lots. Comments show `"<strategy> <magic>"` in MT5.
- **Trailing twin:** once 1 ATR in profit the SL trails 1.2 ATR behind price.
- **Backtest offline:** use MT5 Strategy Tester on FTTestEA -- no terminal
  session or Python needed.
- **Demo-only guard built in:** the EA refuses real-money accounts unless
  `InpAllowReal=true` is set deliberately.
- **Note:** an EA only trades while the MT5 terminal is running. To keep it
  alive unattended, run MT5 on a VPS or enable its auto-start yourself (this
  project will never launch MT5 by itself).

## AetherFlowEA (SMC Flow indicator port)

`mql5/AetherFlowEA.mq5` is an MQL5 port of the "🔱 SMC Flow System" Pine Script
v6 indicator (AETHER FLOW SYSTEM by Fatich.id) as a trading EA. All signal
engines are ported and replayed over closed bars (no repaint, restart-safe):

- **UT Bot** (ATR trailing stop flip, Key Value + ATR Period, optional HA source)
- **Hull Suite** (HMA/THMA/EHMA, used as an optional trend filter)
- **SMC market structure** (externals/internals CHoCH/BOS with swing tracking)
- **FVG** (fair value gaps with mitigation + retest detection)
- **LuxAlgo-style Order Blocks** (volume pivot + Wick mitigation + retest)
- **Three-Bar Reversal** (optional MA cloud / Supertrend / Donchian trend filter)
- **Reversal Signals** (TD-style momentum count)

Trading modes (`InpTradingMode`):
- `UT Bot signals only` - trade UT Bot flips (close opposite, open new side)
- `Confluence` - trade when at least `InpMinConfluence` modules agree and at
  least one "hard" module (UT, external structure, 3BR, FVG/OB retest) fired
- `No trading - chart signals only` - dashboard shows every module's state

SL/TP are always set (ATR multiples, `Risk` group) and the trailing-SL twin
logic is identical to FTTestEA. **Demo-only guard built in**: refuses real-money
accounts unless `InpAllowReal=true`. Magic convention: 9500xx fixed /
9600xx trailing. Build it with `scripts\compile_ea.bat` (compiles both EAs),
or run the MT5 Strategy Tester on it directly.

## Getting help

- Server docs: https://github.com/ariadng/metatrader-mcp-server
- Trading carries risk of loss. You are responsible for every order executed
  through this integration. Not financial advice.
