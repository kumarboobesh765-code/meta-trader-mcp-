//+------------------------------------------------------------------+
//| FTTest_liquiditysweep.mq5 - H4 sweep-and-reclaim, limit entries   |
//| (A/B port of the user's compiled LiquiditySweepH4, chart 38,      |
//| magic 930015 fixed twin; params 48 / 0.20 / 0.05 from the 90d     |
//| backtest: fixed +$433, trail weaker -> no -T twin in this A/B)    |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_LIQUIDITYSWEEP
#define EA_TITLE    "liquiditysweep"
#include "FTTestCore.mqh"
