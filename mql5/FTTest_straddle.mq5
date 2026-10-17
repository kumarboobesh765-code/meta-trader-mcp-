//+------------------------------------------------------------------+
//| FTTest_straddle.mq5 - hourly dual-stop straddle on H1             |
//| Magic map: 930004 fixed / 940004 trailing (-T twin)               |
//|                                                                   |
//| All logic lives in FTTestCore.mqh: SigStraddle() forms the 4-bar  |
//| range from the last four CLOSED H1 bars and calls ArmDual() with  |
//| a 0.25-ATR buffer beyond range high/low. ArmDual() keys one       |
//| trade per H1 hour, cancels the far side once filled and retries   |
//| a failed send every few seconds. Order SL/TP = entry +/- 1 ATR.   |
//| Backtest reference (scripts/backtest_straddle.py etc.):          |
//|   fixed +$14.00 / trail +$53.50 (1:3 R:R, 68% win).               |
//|                                                                   |
//| Run it on the H1 host chart -- InpTimeframe=H1 (preset 16385).    |
//| Fixed twin preset:  FTTestEA_straddle_fixed.set    magic 930004   |
//| Trailing twin:      FTTestEA_straddle_trailing.set magic 940004   |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_STRADDLE
#define EA_TITLE    "straddle"
#include "FTTestCore.mqh"
