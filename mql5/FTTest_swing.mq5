//+------------------------------------------------------------------+
//| FTTest_swing.mq5 - H1 structure bias + M15/M30 EMA21 pullback    |
//| (fixed/trailing twins, magics 930018 / 940018)                    |
//|                                                                   |
//| Backtest 2026-10-05 (593d span, 30d windows rolled every 10d):   |
//|   M15 52/52 windows profitable   fixed +1262.52 / trail +15016.71 |
//|   M30 52/52 windows profitable   fixed +3017.91 / trail +10125.12 |
//|   H1  49/52 -> DECAYS, so H1 is deliberately NOT deployed.        |
//| Fixed loses to trailing on every timeframe tested.               |
//|                                                                   |
//| Signal + stop logic: SigSwing() in FTTestCore.mqh.               |
//| This file only selects the strategy, exactly like every other     |
//| FTTest family EA.                                                 |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#define EA_STRATEGY FT_SWING
#define EA_TITLE    "swing"
#include "FTTestCore.mqh"