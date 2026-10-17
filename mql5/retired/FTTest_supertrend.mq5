//+------------------------------------------------------------------+
//| FTTest_supertrend.mq5 - Pine ta.supertrend flip (RMA ATR)         |
//| (fixed/trailing twins, magics 930014 / 940014, H1 host chart)     |
//| Faithful port: scripts/backtest_supertrend.py st_dir_pine();      |
//| params 5 x 2.0 picked from the 2026-09-30 corrected sweep         |
//| (H1 90d: fixed +$304.54 PF 1.50, trail +$255.24 PF 1.51).       |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_SUPERTREND
#define EA_TITLE    "supertrend"
#include "FTTestCore.mqh"
