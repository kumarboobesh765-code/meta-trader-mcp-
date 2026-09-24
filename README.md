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

## Getting help

- Server docs: https://github.com/ariadng/metatrader-mcp-server
- Trading carries risk of loss. You are responsible for every order executed
  through this integration. Not financial advice.
