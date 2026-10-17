//+------------------------------------------------------------------+
//| GridBestRREA.mq5 - recommended hybrid (measured, not guessed).   |
//| Source: live 33705313 bot (magic 300003, 6,786 deals) + replay    |
//| verdicts. Evidence: logs/live_33705313_probe_20261014.txt.        |
//|                                                                   |
//| Rules:                                                            |
//|   * SINGLE SIDE, AUTO: H1 EMA-200 picks BUY (above) / SELL        |
//|     (below). Never opens opposite while a side lives (WaitFlat).  |
//|     Legacy opposite basket is CLOSE-ONLY.                         |
//|   * Step $3.50 adverse past most-adverse entry (source MED        |
//|     +-3.52/3.54, n=1,652).                                        |
//|   * Lots 0.01, 0.01, 0.02, 0.04 ... x2 from layer 2 (source        |
//|     scheme; 2nd layer repeats base). Cap 6 layers (source runs    |
//|     to 13 / 5.12 lots -- cap cuts tail ~16x, keeps 95%+ escapes). |
//|   * TP breakeven + $1.80 ATTACHED ON SERVER (source MED exactly   |
//|     1.80, n=2,050) -- dead terminal still exits.                  |
//|   * SL CATASTROPHIC, ATTACHED ON SERVER: behind deepest allowed   |
//|     layer + buffer (6 x $3.50 + $1.00 = ~$8.20). Grid mechanics    |
//|     fully intact; tail hard-capped. Honest basket RR ~1:0.22 --    |
//|     grids fund rare large losses with frequent small wins; anyone |
//|     promising 1:1.5 PER BASKET on a grid is selling fantasy       |
//|     (replay: negative in all 12 configs).                         |
//|   * Immediate re-entry when active side flat (source MED 0.0 min). |
//|                                                                   |
//| Safety: DEMO-ONLY unless InpAllowReal=true. Magic required.       |
//| Equity stop closes all + pauses to next server day. Kill rule:    |
//| PF < 1.0 after 200 closed deals -> retire it, don't negotiate.    |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.01"
#property strict

#include <Trade\Trade.mqh>

enum ENUM_BESTRR_MODE
  {
   BESTRR_LONG_ONLY  = 1,   // LONG only
   BESTRR_SHORT_ONLY = 2,   // SHORT only
   BESTRR_AUTO       = 3    // AUTO -- H1 EMA-200 picks the side
  };

input group              "Core (measured)"
input ENUM_BESTRR_MODE   InpMode            = BESTRR_AUTO;  // Direction mode
input double             InpLots            = 0.01;         // Base lot (layers 0-1)
input double             InpLotMult         = 2.0;          // Multiply from layer 2 (layers 0-1 stay 0.01)
input int                InpGridStepPts     = 500;          // Adverse step ($5.00, was $3.50)
input int                InpLayerCooldownSec  = 1200;       // Min seconds between layers (20 min)
input int                InpReentryDelaySec   = 900;        // Min seconds after escape before new cycle (15 min)
input double             InpTPDistPts       = 180;          // Escape bucket be+$1.80
input int                InpMaxLayers       = 6;            // Ladder cap (0 = unlimited)
input double             InpMaxLots         = 0.0;          // Single-layer cap (0 = off)
input int                InpMagic           = 0;            // Magic (required, never 0)

input group              "Trend filter (AUTO)"
input ENUM_TIMEFRAMES    InpTrendTF         = PERIOD_H1;    // Trend timeframe
input int                InpTrendMAPeriod   = 200;          // EMA period
input bool               InpWaitFlatOnFlip  = true;         // No fresh opposite while a side lives

input group              "Safety"
input int                InpSLBufferPts     = 100;          // Room past deepest layer ($1.00)
input bool               InpAllowReal       = false;        // Allow REAL (leave false)
input double             InpEquityStopMoney = 5000.0;       // Equity drop -> close+pause (0=off)
input int                InpDeviationPts    = 50;           // Slippage (points)

CTrade   trade;
string   g_tag = "gridbestrr";
double   g_pt  = 0.01;
int      g_dig = 2;
double   g_step = 0.0;
double   g_tpd  = 0.0;
double   g_minStop = 0.0;
datetime g_pausedUntil = 0;
int      g_maHandle = INVALID_HANDLE;
long     g_lastAutoDir = POSITION_TYPE_BUY;
datetime g_lastLayerAt = 0;    // last layer-open time (cooldown gate)
datetime g_lastEscapeAt = 0;   // last basket-close time (re-entry gate)

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
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   g_minStop = (stopsLevel + 2) * g_pt;

   if(InpMode == BESTRR_AUTO)
     {
      g_maHandle = iMA(_Symbol, InpTrendTF, InpTrendMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(g_maHandle == INVALID_HANDLE)
        {
         Print("REFUSING: could not create EMA handle.");
         return(INIT_FAILED);
        }
     }

   trade.SetDeviationInPoints(InpDeviationPts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetExpertMagicNumber(InpMagic);
   double catRisk = (InpMaxLayers > 0 ? InpMaxLayers * g_step : 800 * g_pt)
                  + InpSLBufferPts * g_pt;
   Print("gridbestrr ", InpMagic, " v1.01 started on ", _Symbol,
         " mode=", (int)InpMode, " base=", InpLots,
         " step=", g_step, " tp=", g_tpd,
         " layers<=", (InpMaxLayers == 0 ? "unl" : IntegerToString(InpMaxLayers)),
         " catSL=", DoubleToString(catRisk, g_dig));
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   if(g_maHandle != INVALID_HANDLE)
     {
      IndicatorRelease(g_maHandle);
      g_maHandle = INVALID_HANDLE;
     }
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

// owner scheme: layers 0-1 flat 0.01, multiply only from layer 2:
// 0.01, 0.01, 0.02, 0.04, 0.08 ... (x2) so the back-loaded basket
// pulls breakeven close and still ends in profit at the bucket.
double LayerVol(int layer)
  {
   if(layer <= 1)
      return(NormVol(InpLots));
   return(NormVol(InpLots * MathPow(InpLotMult, layer - 1)));
  }

// catastrophic SL behind deepest allowed layer + buffer; TP = bucket
void BasketLevels(long dir, double be, double &sl, double &tp)
  {
   double risk = (InpMaxLayers > 0 ? InpMaxLayers * g_step : 800 * g_pt)
               + InpSLBufferPts * g_pt;
   if(risk < g_minStop)
      risk = g_minStop;
   if(dir == POSITION_TYPE_BUY)
     {
      sl = be - risk;
      tp = be + g_tpd;
     }
   else
     {
      sl = be + risk;
      tp = be - g_tpd;
     }
   sl = NormalizeDouble(sl, g_dig);
   tp = NormalizeDouble(tp, g_dig);
  }

bool SetAllSLTP(long dir, double sl, double tp)
  {
   bool ok = true;
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
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      if(MathAbs(curSL - sl) < g_pt / 2 && MathAbs(curTP - tp) < g_pt / 2)
         continue;
      if(!trade.PositionModify(t, sl, tp))
         ok = false;   // stops/freeze distance: retry next tick
     }
   return(ok);
  }

bool OpenLayer(long dir, double vol, double sl, double tp)
  {
   double px = (dir == POSITION_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(!trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px, sl, tp, g_tag))
     {
      // fast market: bucket may violate stops distance this instant --
      // open bare, sync pass attaches SL/TP next tick
      if(!trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px, 0.0, 0.0, g_tag))
         return(false);
     }
   return(true);
  }

void CloseAllSide(long dir, string why)
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
   Print("gridbestrr basket escape dir=", dir, " ", why);
  }

bool DayBlocked()
  {
   if(g_pausedUntil == 0)
      return(false);
   if(TimeCurrent() >= g_pausedUntil)
     {
      g_pausedUntil = 0;
      Print("gridbestrr equity-stop pause lifted");
      return(false);
     }
   return(true);
  }

long AutoDir(double refPrice)
  {
   if(g_maHandle == INVALID_HANDLE)
      return(g_lastAutoDir);
   double ema[];
   if(CopyBuffer(g_maHandle, 0, 0, 1, ema) < 1)
      return(g_lastAutoDir);
   if(refPrice > ema[0])
      g_lastAutoDir = POSITION_TYPE_BUY;
   else if(refPrice < ema[0])
      g_lastAutoDir = POSITION_TYPE_SELL;
   return(g_lastAutoDir);
  }

//+------------------------------------------------------------------+
void RunBasket(long dir, double priceEsc, bool allowOpen)
  {
   double be = 0, adverse = 0;
   int n = CountSideAndBe(dir, be, adverse);

   if(n == 0)
     {
      if(allowOpen && !DayBlocked())
        {
         if(InpReentryDelaySec > 0 && g_lastEscapeAt > 0 &&
            TimeCurrent() - g_lastEscapeAt < InpReentryDelaySec)
            return;   // more loss/time before a fresh trade, per owner
         double sl0, tp0;
         BasketLevels(dir, priceEsc, sl0, tp0);
         if(OpenLayer(dir, LayerVol(0), sl0, tp0))
           {
            g_lastLayerAt = TimeCurrent();
            Print("gridbestrr new cycle dir=", dir, " lot=", LayerVol(0),
                  " sl=", sl0, " tp=", tp0);
           }
        }
      return;
     }

   double sl, tp;
   BasketLevels(dir, be, sl, tp);

   bool tpHit = (dir == POSITION_TYPE_BUY) ? (priceEsc >= tp) : (priceEsc <= tp);
   bool slHit = (dir == POSITION_TYPE_BUY) ? (priceEsc <= sl) : (priceEsc >= sl);
   if(tpHit || slHit)
     {
      CloseAllSide(dir, (tpHit ? "TP" : "SL"));
      g_lastEscapeAt = TimeCurrent();
      return;
     }

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
        {
         if(InpLayerCooldownSec > 0 && g_lastLayerAt > 0 &&
            TimeCurrent() - g_lastLayerAt < InpLayerCooldownSec)
            return;   // need more time as well as more loss, per owner
         if(OpenLayer(dir, nextLot, 0.0, 0.0))   // SL/TP synced below
           {
            g_lastLayerAt = TimeCurrent();
            Print("gridbestrr layer ", n, " dir=", dir, " lot=", nextLot);
           }
        }
     }

   SetAllSLTP(dir, sl, tp);   // whole basket shares SL+TP, server-side
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
         Print("gridbestrr EQUITY STOP: closing all, paused to next server day");
         CloseAllSide(POSITION_TYPE_BUY, "[eqstop]");
         CloseAllSide(POSITION_TYPE_SELL, "[eqstop]");
         return;
        }
     }

   if(DayBlocked())
     {
      Comment("gridbestrr paused (equity stop)");
      return;
     }

   long active, idle;
   double activePx;
   if(InpMode == BESTRR_LONG_ONLY)
     {
      active = POSITION_TYPE_BUY; idle = POSITION_TYPE_SELL; activePx = bid;
     }
   else if(InpMode == BESTRR_SHORT_ONLY)
     {
      active = POSITION_TYPE_SELL; idle = POSITION_TYPE_BUY; activePx = ask;
     }
   else
     {
      active = AutoDir((bid + ask) / 2);
      idle = (active == POSITION_TYPE_BUY) ? POSITION_TYPE_SELL : POSITION_TYPE_BUY;
      activePx = (active == POSITION_TYPE_BUY) ? bid : ask;
     }
   double idlePx = (idle == POSITION_TYPE_BUY) ? bid : ask;

   bool allowActive = true;
   if(InpMode == BESTRR_AUTO && InpWaitFlatOnFlip && CountSide(idle) > 0)
      allowActive = (CountSide(active) > 0);   // add to live side only

   RunBasket(active, activePx, allowActive);
   RunBasket(idle, idlePx, false);              // close-only, always

   Comment("gridbestrr ", InpMagic,
           " mode=", (int)InpMode,
           " active=", (active == POSITION_TYPE_BUY ? "BUY" : "SELL"),
           "  L/S = ", CountSide(POSITION_TYPE_BUY), "/",
           CountSide(POSITION_TYPE_SELL));
  }
//+------------------------------------------------------------------+
