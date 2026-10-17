//+------------------------------------------------------------------+
//| FTTest_fixfade.mq5 - London Fix rebalancing fade (M15)            |
//| Repurposes the dead orderflow slot: charts 23/24, magics          |
//| 930009/940009 kept append-only (orderflow logged zero trades).    |
//| Backtest (90d): 46 trips +$140 PF 6.17 win 76% -> fixed + trail   |
//| twins; 13-14 UTC impulse >= 0.5 ATR faded at 14:15, TP 1x impulse,|
//| 8-bar time stop.                                                  |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_FIXFADE
#define EA_TITLE    "fixfade"
#include "FTTestCore.mqh"
