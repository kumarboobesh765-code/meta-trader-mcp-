//+------------------------------------------------------------------+
//| FTTest_orderflow.mq5 - order-flow imbalance + absorption          |
//| (fixed/trailing twins)                                            |
//| Magic map: 930009 fixed / 940009 trailing                         |
//| Attach to an M1 chart: the engine reads the closed M1 series and  |
//| buckets live tick flow by minute (TICK_FLAG_BUY/SELL when the     |
//| broker sends them, tick rule otherwise).                          |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_ORDERFLOW
#define EA_TITLE    "orderflow"
#include "FTTestCore.mqh"
