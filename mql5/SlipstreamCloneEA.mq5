//+------------------------------------------------------------------+
//| SlipstreamCloneEA.mq5 - faithful clone of the live account       |
//| 33705313 bot (magic 300003, "slipstream-gridbot", 6,786 deals     |
//| captured 2026-09-17..10-14, probe log                            |
//| logs/live_33705313_probe_20261014.txt).                          |
//|                                                                   |
//| Measured rules (no guessing):                                     |
//|   * SOURCE runs BOTH sides (97.4% overlap) -- this build is       |
//|     SINGLE-SIDE ONLY per user request: InpCloneMode selects LONG  |
//|     or SHORT. Only that side opens cycles/layers. A legacy        |
//|     opposite basket is managed CLOSE-ONLY (bucket kept, escapes,  |
//|     never adds). New cycle opens immediately when the active side |
//|     goes flat (source median re-entry gap 0.0 min).               |
//|   * Layer step $3.50 adverse past most-adverse entry (buy MED     |
//|     -3.52 / sell MED +3.54, modes -3.5/+3.5, n=1,652).            |
//|   * Lots per layer index: 0.01, 0.01, 0.02, 0.04, ... x2          |
//|     (2nd layer repeats 0.01; doubling starts at layer 3). Max     |
//|     observed run: 13 consecutive same-side entries (up to 5.12).  |
//|   * EVERY side escapes at breakeven + $1.80 (true lone exits     |
//|     n=2,050, MED exactly 1.80 both sides; 9-16% scratched near    |
//|     breakeven-minus-spread; overshoot to +4.6 on spikes = manual |
//|     close lag, no server TP). Batch closes tagged "[tp X]".      |
//|   * Closes are MANUAL batch closes tagged "[tp X]" (3,097); zero |
//|     server SL/TP ever attached (orders probe: 0 with SL/TP).      |
//|   * No stop-loss anywhere. Closed win rate 69-70% per side, net   |
//|     +12,525 USC (~+$125) in ~4 weeks on ~$1k.                     |
//|                                                                   |
//| Safety rails (NOT part of the source; demo survival):             |
//|   * DEMO-ONLY unless InpAllowReal=true. Magic required.           |
//|   * InpMaxLayers (default 12 ~ observed max 13) + InpMaxLots.      |
//|   * InpEquityStopMoney closes all + pauses to next server day.    |
//| Set caps to 0 to remove them. No SL is ever attached, faithful.   |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.01"
#property strict

#include <Trade\Trade.mqh>

enum ENUM_CLONE_MODE
  {
   CLONE_LONG_ONLY  = 1,   // LONG only -- BUY side trades, SELL close-only
   CLONE_SHORT_ONLY = 2    // SHORT only -- SELL side trades, BUY close-only
  };

input group   "Core (measured)"
input ENUM_CLONE_MODE InpCloneMode = CLONE_LONG_ONLY;  // Trading side (single-side only)
input double  InpLots            = 0.01;   // Base lot (layers 0 and 1)
input double  InpLotMult         = 2.0;    // Doubling from layer 2 on
input int     InpGridStepPts     = 350;    // Adverse step per layer, points ($3.50)
input double  InpTPDistPts       = 180;    // Escape bucket be+TP, points ($1.80)
input int     InpMaxLayers       = 12;     // Ladder cap, layers (0 = unlimited)
input double  InpMaxLots         = 0.0;    // Single-layer lot cap (0 = unlimited)
input int     InpMagic           = 0;      // Magic (must be set, never 0)

input group   "Safety (not in source)"
input bool    InpAllowReal       = false;  // Allow REAL accounts (leave false)
input double  InpEquityStopMoney = 5000.0; // Equity drop vs balance -> close all + pause (0 = off)
input int     InpDeviationPts    = 50;     // Max slippage (points)

CTrade   trade;
string   g_openTag = "slipstream-clone";
double   g_pt  = 0.01;
int      g_dig = 2;
double   g_step = 0.0;
double   g_tpd = 0.0;
datetime g_pausedUntil = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpMagic <= 0)
     {
      Print("REFUSING: InpMagic must be set explicitly.");
      return(INIT_FAILED);
     }
   ENUM_ACCOUNT_TRADE_MODE mode =
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_REAL && !InpAllowReal)
     {
      Print("REFUSING: real-money account and InpAllowReal=false.");
      return(INIT_FAILED);
     }
   g_pt  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(g_pt <= 0)
      g_pt = 0.01;
   g_dig = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_step = InpGridStepPts * g_pt;
   g_tpd  = InpTPDistPts * g_pt;
   if(g_step <= 0 || g_tpd <= 0)
     {
      Print("REFUSING: grid step / TP must be > 0.");
      return(INIT_FAILED);
     }
   trade.SetDeviationInPoints(InpDeviationPts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetExpertMagicNumber(InpMagic);
   Print("slipstream-clone ", InpMagic, " v1.01 started on ", _Symbol,
         " mode=", (int)InpCloneMode,
         " base=", InpLots, " step=", g_step,
         " tp=", g_tpd,
         " layers<=", (InpMaxLayers == 0 ? "unl" : IntegerToString(InpMaxLayers)));
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   Comment("");
  }

//+------------------------------------------------------------------+
int CountSideAndBe(long dir, double &be, double &adverse)
  {
   double sumPV = 0, sumV = 0;
   be = 0; adverse = 0;
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != dir)
         continue;
      double v  = PositionGetDouble(POSITION_VOLUME);
      double px = PositionGetDouble(POSITION_PRICE_OPEN);
      sumPV += v * px;
      sumV  += v;
      if(n == 0)
         adverse = px;
      else if(dir == POSITION_TYPE_BUY)
         adverse = MathMin(adverse, px);
      else
         adverse = MathMax(adverse, px);
      n++;
     }
   if(sumV > 0)
      be = sumPV / sumV;
   return(n);
  }

int CountSide(long dir)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != dir)
         continue;
      n++;
     }
   return(n);
  }

double NormVol(double v)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0)
      v = MathFloor(v / step + 0.0000001) * step;
   if(v < vmin)
      v = vmin;
   if(vmax > 0 && v > vmax)
      v = vmax;
   return(v);
  }

// layer lots: 0.01, 0.01, 0.02, 0.04, ... (doubling starts at layer 2)
double LayerVol(int layer)
  {
   if(layer <= 1)
      return(NormVol(InpLots));
   return(NormVol(InpLots * MathPow(InpLotMult, layer - 1)));
  }

bool OpenLayer(long dir, double vol)
  {
   double px = (dir == POSITION_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return(trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px,
                             0.0, 0.0, g_openTag));   // never any SL/TP, faithful
  }

void CloseAllSide(long dir, string tag)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != dir)
         continue;
      trade.PositionClose(t, InpDeviationPts);
     }
   Print("slipstream-clone basket escape dir=", dir, " tag=", tag);
  }

bool DayBlocked()
  {
   if(g_pausedUntil == 0)
      return(false);
   if(TimeCurrent() >= g_pausedUntil)
     {
      g_pausedUntil = 0;
      Print("slipstream-clone equity-stop pause lifted");
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
void RunBasket(long dir, double priceEsc, bool allowOpen)
  {
   double be = 0, adverse = 0;
   int n = CountSideAndBe(dir, be, adverse);

   if(n == 0)
     {
      if(allowOpen && !DayBlocked())
         OpenLayer(dir, LayerVol(0));      // immediate new cycle, active side only
      return;
     }

   // escape: whole side (lone or basket) at breakeven + $1.80 (measured
   // MED exactly 1.80, n=2,050 true lone exits). Manual close, no server TP.
   double bucket = be + ((dir == POSITION_TYPE_BUY) ? g_tpd : -g_tpd);
   bool hit = (dir == POSITION_TYPE_BUY) ? (priceEsc >= bucket) : (priceEsc <= bucket);
   if(hit)
     {
      string tag = "[tp " + DoubleToString(bucket, g_dig) + "]";
      CloseAllSide(dir, tag);
      return;
     }

   // layer trigger: $3.50 past most-adverse entry (active side only)
   if(allowOpen)
     {
      if(InpMaxLayers > 0 && n >= InpMaxLayers)
         return;
      double nextLot = LayerVol(n);
      if(InpMaxLots > 0 && nextLot > InpMaxLots + 0.0000001)
         return;
      bool trig = (dir == POSITION_TYPE_BUY) ? (priceEsc <= adverse - g_step)
                                             : (priceEsc >= adverse + g_step);
      if(trig)
         OpenLayer(dir, nextLot);
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;

   if(InpEquityStopMoney > 0)
     {
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq < bal - InpEquityStopMoney)
        {
         datetime now = TimeCurrent();
         g_pausedUntil = now - (now % 86400) + 86400;
         Print("slipstream-clone EQUITY STOP: closing all, paused to next server day");
         CloseAllSide(POSITION_TYPE_BUY, "[eqstop]");
         CloseAllSide(POSITION_TYPE_SELL, "[eqstop]");
         return;
        }
     }

   if(DayBlocked())
     {
      Comment("slipstream-clone paused (equity stop)");
      return;
     }

   // single side only: active side opens, idle side is close-only
   if(InpCloneMode == CLONE_LONG_ONLY)
     {
      RunBasket(POSITION_TYPE_BUY, bid, true);
      RunBasket(POSITION_TYPE_SELL, ask, false);
     }
   else
     {
      RunBasket(POSITION_TYPE_SELL, ask, true);
      RunBasket(POSITION_TYPE_BUY, bid, false);
     }

   Comment("slipstream-clone ", InpMagic,
           " mode=", (int)InpCloneMode,
           "  L/S = ", CountSide(POSITION_TYPE_BUY), "/",
           CountSide(POSITION_TYPE_SELL));
  }
//+------------------------------------------------------------------+
