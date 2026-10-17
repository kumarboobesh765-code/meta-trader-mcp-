//+------------------------------------------------------------------+
//| FTTest_sweepabs.mq5 - M15 sweep + volume absorption, market entry  |
//| (fixed/trailing twins, magics 930020 / 940020)                     |
//|                                                                    |
//| Backtest 2026-10-06 (scripts/backtest_institutional_v2.py, 200d,   |
//| cost-aware): fixed -$987 / trail +$1087 PF 1.30 win 68%. The buy  |
//| branch of the original engine NEVER fired ((low-close) >= wick is |
//| impossible); fixed to (close-low) and re-validated two-sided      |
//| (509 buys + 566 sells) before this EA was written.                |
//|                                                                    |
//| Signal + stop logic: SigSweepAbs() in FTTestCore.mqh.              |
//| This file only selects the strategy, exactly like every other     |
//| FTTest family EA.                                                 |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_SWEEPABS
#define EA_TITLE    "sweepabs"
#include "FTTestCore.mqh"
