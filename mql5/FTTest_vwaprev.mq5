//+------------------------------------------------------------------+
//| FTTest_vwaprev.mq5 - session-VWAP band reversion (M15)            |
//| Repurposes the dead supres slot: charts 31/32, magics             |
//| 930013/940013 kept append-only (supres: WF bleed, fixed only).    |
//| Backtest (90d): 86 trips +$95 PF 1.21 win 58% -> fixed + trail    |
//| twins; 1.5-sigma band fade to VWAP, TP = VWAP, 16-bar time stop.  |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_VWAPREV
#define EA_TITLE    "vwaprev"
#include "FTTestCore.mqh"
