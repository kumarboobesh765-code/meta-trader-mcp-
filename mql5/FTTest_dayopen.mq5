//+------------------------------------------------------------------+
//| FTTest_dayopen.mq5 - weekday server-day-open long (M15)           |
//| Pattern: the first tradeable moment of the server day (~01:05,    |
//| = 22:05 UTC) starts a persistent upward drift. Backtest (M15,     |
//| 180d, costs + pessimistic fills): +$796 PF 1.40 win 46%;          |
//| weekday-only (skip >3h weekend gap = Monday) +$788 avg +$5.32     |
//| n=148. Matched-time long controls at 11:00/18:00 lose money, so   |
//| this is not trend beta. Entry at the first tick after the daily   |
//| break, SL 2.0x ATR96, no TP, 16-bar time stop. Fixed exit only    |
//| (trail grid clearly weaker: +$170 vs +$796). Magic 930017.        |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_DAYOPEN
#define EA_TITLE    "dayopen"
#include "FTTestCore.mqh"
