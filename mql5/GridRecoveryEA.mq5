//+------------------------------------------------------------------+
//| GridRecoveryEA.mq5 - single-side recovery grid with RR-based SL  |
//| A disciplined port of the "slipstream-gridbot" behavior observed |
//| on account 33705313 (magic 300003, 6,816 deals):                 |
//|   * ONE direction trades at a time. InpGridMode selects LONG     |
//|     only, SHORT only, or AUTO (H1 EMA trend filter picks the     |
//|     side). Opposite-direction baskets are NEVER opened.          |
//|   * When the basket is empty, a base-lot market position opens    |
//|     (new cycle) with SL/TP attached. The SL is CATASTROPHIC: it  |
//|     sits behind the deepest allowed layer, so the grid can layer |
//|     and escape normally while the tail is hard-capped:           |
//|       BUY : SL = breakeven - (MaxLayers*GridStep + Buffer)       |
//|       SELL: SL = breakeven + (MaxLayers*GridStep + Buffer)       |
//|       TP  = breakeven +/- TPdist (the micro-target bucket).      |
//|     Backtest verdict (19mo M15): a tight per-basket SL fires     |
//|     before layering can work and bleeds in every config; the     |
//|     catastrophic SL preserves the ~100%-closed-win profile.      |
//|   * When price runs AGAINST the basket by GridStep points past    |
//|     the most adverse entry, a new layer is added with volume      |
//|     = base lot * LotMult^layerIndex (0.01 -> 0.02 -> 0.04 ...).   |
//|     All positions of the side then get SL/TP re-synced to the     |
//|     new shared bucket (breakeven +/- offsets), so the whole      |
//|     cluster escapes together.                                    |
//|   * A legacy opposite-side basket (e.g. left over from the old    |
//|     hedged version) is managed CLOSE-ONLY: TP bucket kept in     |
//|     sync, batch-close on escape, but no new layers are added.    |
//|                                                                   |
//| Safety rails (defaults ON -- this genre has real tail risk):      |
//|   * DEMO-ONLY: refuses a REAL account unless InpAllowReal=true.   |
//|   * InpMaxLayers caps the escalation ladder (0 = unlimited).      |
//|   * InpMaxLots caps any single layer's volume (0 = unlimited).    |
//|   * InpEquityStopMoney: if equity falls this far below balance,   |
//|     everything closes and the EA pauses until next server day.    |
//|   * InpWaitFlatOnFlip: in AUTO mode, no new opposite basket       |
//|     while the old side is still open (strict no-hedge).          |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "2.02"
#property strict

#include <Trade\Trade.mqh>

enum ENUM_GRID_MODE
  {
   GRID_LONG_ONLY  = 1,   // LONG only -- BUY basket, never SELL
   GRID_SHORT_ONLY = 2,   // SHORT only -- SELL basket, never BUY
   GRID_AUTO       = 3    // AUTO -- H1 EMA trend filter picks the side
  };

input group          "Core"
input ENUM_GRID_MODE InpGridMode        = GRID_AUTO;      // Direction mode
input double         InpLots            = 0.01;           // Base lot (layer 0)
input double         InpLotMult         = 1.5;            // Lot multiplier per layer (was 2.0: tail risk)
input int            InpMagic           = 0;              // Magic (must be set, never 0)

input group          "Grid engine"
input int            InpGridStepPts     = 120;            // Adverse distance per new layer (points)
input double         InpTPDistPts       = 180;            // TP offset beyond breakeven (points)
input int            InpMaxLayers       = 4;              // Max ladder depth (0 = unlimited; was 6)
input double         InpMaxLots         = 0.0;            // Max single-layer lot (0 = unlimited)

input group          "Risk / Reward"
input int            InpSLBufferPts     = 100;            // Extra room beyond deepest layer before SL (points)
input int            InpCatStopPts      = 800;            // Catastrophic SL distance if MaxLayers=0 (points)
input int            InpDeviationPts    = 50;             // Max slippage (points)

input group          "Trend filter (AUTO mode)"
input ENUM_TIMEFRAMES InpTrendTF        = PERIOD_H1;      // Trend timeframe
input int            InpTrendMAPeriod   = 200;            // EMA period for direction
input int            InpTrendFlatPts    = 0;              // Dead-band around EMA (points, 0 = off)
input bool           InpWaitFlatOnFlip  = true;           // In AUTO: no new opposite basket while old side open

input group          "News filter"
input bool           InpNewsFilter      = true;           // Pause NEW cycles/layers around high-impact news
input int            InpNewsPauseMin    = 30;             // Pause this many minutes before AND after each event
input string         InpNewsCurrency    = "USD";          // Currency of events to watch

input group          "Safety"
input bool           InpAllowReal       = false;          // Allow REAL accounts (leave false)
input double         InpEquityStopMoney = 5000.0;         // Equity drop vs balance -> close all + pause (0 = off)

CTrade   trade;
string   g_tag = "gridrecovery";
double   g_pt  = 0.01;
int      g_dig = 2;
double   g_step = 0.0;
double   g_tpd  = 0.0;
double   g_minStop = 0.0;
datetime g_pausedUntil = 0;
int      g_maHandle = INVALID_HANDLE;
long     g_lastAutoDir = POSITION_TYPE_BUY;
datetime g_newsTimes[];
datetime g_newsRefresh = 0;
bool     g_newsHeld = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpMagic <= 0)
     {
      Print("REFUSING: InpMagic must be set explicitly. Load a preset or type it in.");
      return(INIT_FAILED);
     }
   ENUM_ACCOUNT_TRADE_MODE mode =
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_REAL && !InpAllowReal)
     {
      Print("REFUSING: real-money account and InpAllowReal=false. ",
            "Grid/martingale on a real account is a deliberate decision.");
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
      Print("REFUSING: grid step / TP offset must be > 0 points.");
      return(INIT_FAILED);
     }
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   g_minStop = (stopsLevel + 2) * g_pt;   // small cushion above broker minimum

   if(InpGridMode == GRID_AUTO)
     {
      g_maHandle = iMA(_Symbol, InpTrendTF, InpTrendMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(g_maHandle == INVALID_HANDLE)
        {
         Print("REFUSING: could not create EMA handle for trend filter.");
         return(INIT_FAILED);
        }
     }

   trade.SetDeviationInPoints(InpDeviationPts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetExpertMagicNumber(InpMagic);
   double catRisk = (InpMaxLayers > 0 ? InpMaxLayers * g_step : InpCatStopPts * g_pt)
                  + InpSLBufferPts * g_pt;
   Print("gridrecovery ", InpMagic, " v2.02 started on ", _Symbol,
         " mode=", (int)InpGridMode,
         " base=", InpLots, " mult=", InpLotMult,
         " layers<=", (InpMaxLayers == 0 ? "unl" : IntegerToString(InpMaxLayers)),
         " step=", g_step, " tp_off=", g_tpd,
         " catSL=", DoubleToString(catRisk, g_dig),
         " basketRR=1:", DoubleToString(g_tpd / catRisk, 2));
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
//| Position helpers (this EA's positions only: symbol + magic)       |
//+------------------------------------------------------------------+
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
         adverse = MathMin(adverse, px);   // most adverse buy = deepest
      else
         adverse = MathMax(adverse, px);   // most adverse sell = highest
      n++;
     }
   if(sumV > 0)
      be = sumPV / sumV;   // volume-weighted entry (swap/commission excluded)
   return(n);
  }

double BasketFloating(long dir)
  {
   double f = 0;
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
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   return(f);
  }

//+------------------------------------------------------------------+
//| Shared-bucket levels. SL is catastrophic (behind deepest layer);  |
//| TP is the micro-target bucket. Effective basket RR = TPdist/risk.|
//+------------------------------------------------------------------+
void BasketLevels(long dir, double be, double &sl, double &tp)
  {
   double risk = (InpMaxLayers > 0 ? InpMaxLayers * g_step : InpCatStopPts * g_pt)
               + InpSLBufferPts * g_pt;
   if(risk < g_minStop)
      risk = g_minStop;
   double reward = g_tpd;   // micro-target bucket, unchanged by SL design
   if(dir == POSITION_TYPE_BUY)
     {
      sl = be - risk;
      tp = be + reward;
     }
   else
     {
      sl = be + risk;
      tp = be - reward;
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
         continue;                        // already aligned
      if(!trade.PositionModify(t, sl, tp))
         ok = false;                      // stops/freeze distance: retry next tick
     }
   return(ok);
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

bool OpenLayer(long dir, double vol, double sl, double tp)
  {
   double px = (dir == POSITION_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(!trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px, sl, tp, g_tag))
     {
      // fast market: bucket may violate stops/freeze distance this instant --
      // open bare, the sync pass attaches SL/TP on the next tick
      if(!trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px, 0.0, 0.0, g_tag))
         return(false);
     }
   return(true);
  }

void CloseAllSide(long dir)
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
      trade.PositionClose(t);
     }
  }

bool DayBlocked()
  {
   if(g_pausedUntil == 0)
      return(false);
   datetime now = TimeCurrent();
   if(now >= g_pausedUntil)
     {
      g_pausedUntil = 0;
      Print(g_tag, " equity-stop pause lifted");
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| AUTO direction: above EMA -> BUY, below -> SELL (dead-band holds |
//| the last side to avoid flip-flop).                               |
//+------------------------------------------------------------------+
long AutoDir(double refPrice)
  {
   if(g_maHandle == INVALID_HANDLE)
      return(g_lastAutoDir);
   double ema[];
   if(CopyBuffer(g_maHandle, 0, 0, 1, ema) < 1)
      return(g_lastAutoDir);   // no data yet: hold last side
   double band = InpTrendFlatPts * g_pt;
   if(refPrice > ema[0] + band)
      g_lastAutoDir = POSITION_TYPE_BUY;
   else if(refPrice < ema[0] - band)
      g_lastAutoDir = POSITION_TYPE_SELL;
   return(g_lastAutoDir);
  }

//+------------------------------------------------------------------+
//| One side's basket step. allowOpen=false -> close-only management |
//| (legacy opposite basket still escapes, never adds layers).        |
//+------------------------------------------------------------------+
void RunBasket(long dir, double priceEsc, bool allowOpen)
  {
   double be = 0, adverse = 0;
   int n = CountSideAndBe(dir, be, adverse);

   if(n == 0)
     {
      if(!allowOpen || DayBlocked())
         return;
      // new cycle: base lot with SL/TP at perfect RR from the entry price
      double sl0, tp0;
      BasketLevels(dir, priceEsc, sl0, tp0);
      if(OpenLayer(dir, NormVol(InpLots), sl0, tp0))
         Print(g_tag, " new cycle dir=", dir, " lot=", NormVol(InpLots),
               " sl=", sl0, " tp=", tp0);
      return;
     }

   double sl, tp;
   BasketLevels(dir, be, sl, tp);

   // escape check (manual batch close; server SL/TP fire first when attached)
   bool tpHit = (dir == POSITION_TYPE_BUY) ? (priceEsc >= tp) : (priceEsc <= tp);
   bool slHit = (dir == POSITION_TYPE_BUY) ? (priceEsc <= sl) : (priceEsc >= sl);
   if(tpHit || slHit)
     {
      Print(g_tag, " basket escape dir=", dir, (tpHit ? " TP" : " SL"),
            " n=", n, " float=", DoubleToString(BasketFloating(dir), 2));
      CloseAllSide(dir);
      return;
     }

   // layer trigger: price ran a grid step beyond the most adverse entry
   if(allowOpen)
     {
      double nextLot = NormVol(InpLots * MathPow(InpLotMult, n));
      bool capLot = (InpMaxLots > 0 && nextLot > InpMaxLots + 0.0000001);
      bool capLay = (InpMaxLayers > 0 && n >= InpMaxLayers);
      bool trig = (dir == POSITION_TYPE_BUY) ? (priceEsc <= adverse - g_step)
                                             : (priceEsc >= adverse + g_step);
      if(trig && !capLay && !capLot)
        {
         if(OpenLayer(dir, nextLot, 0.0, 0.0))   // SL/TP synced to new bucket below
            Print(g_tag, " layer ", n, " dir=", dir, " lot=", nextLot);
        }
     }

   // keep the shared bucket current for the whole basket
   SetAllSLTP(dir, sl, tp);
  }

//+------------------------------------------------------------------+
//| High-impact news calendar, refreshed hourly. Live/demo only:     |
//| the economic calendar is not available in the strategy tester.   |
//+------------------------------------------------------------------+
void RefreshNews()
  {
   datetime now = TimeCurrent();
   if(now < g_newsRefresh)
      return;
   g_newsRefresh = now + 3600;
   ArrayFree(g_newsTimes);
   MqlCalendarValue vals[];
   if(!CalendarValueHistory(vals, now - 86400, now + 2 * 86400, NULL, InpNewsCurrency))
     {
      Print(g_tag, " news calendar unavailable (err ", GetLastError(), "): news filter inactive");
      return;
     }
   int k = 0;
   for(int i = 0; i < ArraySize(vals); i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(vals[i].event_id, ev))
         continue;
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH)
         continue;
      ArrayResize(g_newsTimes, k + 1);
      g_newsTimes[k++] = vals[i].time;
     }
   Print(g_tag, " news calendar: ", k, " high-impact ", InpNewsCurrency, " events in window");
  }

bool NewsHold()
  {
   if(!InpNewsFilter)
      return(false);
   RefreshNews();
   datetime now = TimeCurrent();
   long win = (long)InpNewsPauseMin * 60;
   bool hold = false;
   for(int i = 0; i < ArraySize(g_newsTimes) && !hold; i++)
      if(MathAbs((long)(now - g_newsTimes[i])) <= win)
         hold = true;
   if(hold != g_newsHeld)
     {
      g_newsHeld = hold;
      Print(g_tag, hold ? " news pause ON: no new cycles/layers"
                        : " news pause OFF: entries resume");
     }
   return(hold);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;                                   // no feed (closed/weekend)

   // equity guard takes priority over everything
   if(InpEquityStopMoney > 0)
     {
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq < bal - InpEquityStopMoney)
        {
         datetime now = TimeCurrent();
         datetime day = now - (now % 86400);
         g_pausedUntil = day + 86400;           // pause until the next server day
         Print(g_tag, " EQUITY STOP: eq=", eq, " fell ", InpEquityStopMoney,
               " below balance; closing all baskets, paused until next server day");
         CloseAllSide(POSITION_TYPE_BUY);
         CloseAllSide(POSITION_TYPE_SELL);
         return;
        }
     }

   if(DayBlocked())
     {
      Comment(g_tag, " paused (equity stop)");
      return;
     }

   long active, idle;
   double activePx;
   if(InpGridMode == GRID_LONG_ONLY)
     {
      active = POSITION_TYPE_BUY; idle = POSITION_TYPE_SELL; activePx = bid;
     }
   else if(InpGridMode == GRID_SHORT_ONLY)
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

   // strict no-hedge: in AUTO with WaitFlat, hold new entries while old side lives
   bool idleOpen = (CountSide(idle) > 0);
   bool allowActive = true;
   if(InpGridMode == GRID_AUTO && InpWaitFlatOnFlip && idleOpen)
      allowActive = (CountSide(active) > 0);   // add to live side only, never open fresh opposite
   if(NewsHold())
      allowActive = false;                     // news window: manage/escape only, no new entries

   RunBasket(active, activePx, allowActive);
   RunBasket(idle, idlePx, false);              // close-only, always

   Comment(g_tag, " ", InpMagic,
           "  mode=", (int)InpGridMode,
           " active=", (active == POSITION_TYPE_BUY ? "BUY" : "SELL"),
           "  bid=", bid, " ask=", ask,
           "  layers L/S = ", CountSide(POSITION_TYPE_BUY), "/",
           CountSide(POSITION_TYPE_SELL));
  }
//+------------------------------------------------------------------+
