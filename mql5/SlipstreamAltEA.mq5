//+------------------------------------------------------------------+
//| SlipstreamAltEA.mq5 - alternating-direction martingale basket     |
//| Based on the measured "slipstream-gridbot" clone behavior, with   |
//| the user-corrected direction rule:                                 |
//|                                                                   |
//|   * ONE cycle at a time, on ONE side. Cycle 1 opens BUY, cycle 2  |
//|     SELL, cycle 3 BUY ... strict alternation after every escaped  |
//|     basket. Direction parity is derived from the deal history of  |
//|     this EA's magic (last entry deal), so terminal restarts or    |
//|     equity-stop pauses cannot desynchronize the flip order.       |
//|   * New cycle opens immediately when the active side is flat      |
//|     (source median re-entry gap 0.0 min).                         |
//|   * Layer added every $4.00 (400 points) adverse past the most    |
//|     adverse entry of the basket.                                  |
//|   * Lot ladder: 0.01, 0.01, 0.02, 0.04, 0.08, ... doubling starts |
//|     at layer 2 (measured from the source's 13-layer history).     |
//|   * Shared basket TP at breakeven + $1.80 (batch close, tagged    |
//|     "[tp ...]"). No stop-loss is ever attached (faithful).        |
//|                                                                   |
//| Safety rails (not in the source; requested):                      |
//|   * InpNewsFilter: no NEW cycles/layers within +/-30 min of a     |
//|     high-impact calendar event for the watched currency. Existing |
//|     baskets keep being managed/escaped during the window.         |
//|   * InpMaxLayers caps the ladder, InpMaxLots caps one layer.      |
//|   * InpEquityStopMoney: equity drop vs balance -> close all +     |
//|     pause until the next server day.                              |
//|   * DEMO-ONLY unless InpAllowReal=true. Magic required.           |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.01"
#property strict

#include <Trade\Trade.mqh>

input group   "Core"
input double  InpLots            = 0.01;   // Base lot (layers 0 and 1)
input double  InpLotMult         = 2.0;    // Doubling from layer 2 on
input int     InpGridStepPts     = 400;    // Adverse step per layer, points ($4.00)
input double  InpTPDistPts       = 180;    // Basket TP beyond breakeven, points ($1.80)
input int     InpMaxLayers       = 12;     // Ladder cap, layers (0 = unlimited)
input double  InpMaxLots         = 0.0;    // Single-layer lot cap (0 = unlimited)
input int     InpMagic           = 0;      // Magic (must be set, never 0)

input group   "News filter"
input bool    InpNewsFilter      = true;   // Pause new cycles/layers around high-impact news
input int     InpNewsPauseMin    = 30;     // Pause this many minutes before AND after each event
input string  InpNewsCurrency    = "USD";  // Currency of events to watch

input group   "Safety"
input bool    InpAllowReal       = false;  // Allow REAL accounts (leave false)
input double  InpEquityStopMoney = 5000.0; // Equity drop vs balance -> close all + pause (0 = off)
input int     InpDeviationPts    = 50;     // Max slippage (points)

CTrade   trade;
string   g_tag = "slipstream-alt";
double   g_pt  = 0.01;
int      g_dig = 2;
double   g_step = 0.0;
double   g_tpd  = 0.0;
datetime g_pausedUntil = 0;
datetime g_newsTimes[];
datetime g_newsRefresh = 0;
bool     g_newsHeld = false;
int      g_prevN = 0;          // positions last tick (0 -> flat transition triggers rescan)
bool     g_historyDirty = true;
double   g_lastBasketTP = 0.0; // live basket escape level for the chart comment
int      g_lastBasketN = 0;    // size of that basket (0 = none live)
long     g_lastBasketDir = -1; // side of that basket

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
   Print(g_tag, " ", InpMagic, " v1.01 started on ", _Symbol,
         " base=", InpLots, " mult=", InpLotMult,
         " step=", g_step, " tp=", g_tpd,
         " layers<=", (InpMaxLayers == 0 ? "unl" : IntegerToString(InpMaxLayers)),
         " news=", (InpNewsFilter ? "on" : "off"));
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
   bool ok = trade.PositionOpen(_Symbol, (ENUM_ORDER_TYPE)dir, vol, px, 0.0, 0.0, g_tag);
   if(ok)
      Print(g_tag, " new cycle dir=", (dir == POSITION_TYPE_BUY ? "BUY" : "SELL"), " lot=", vol);
   else
      Print(g_tag, " open failed err=", GetLastError());
   return(ok);
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
   Print(g_tag, " basket escape dir=",
         (dir == POSITION_TYPE_BUY ? "BUY" : "SELL"), " tag=", tag);
   g_historyDirty = true;                   // flip parity now judged from history
  }

//+------------------------------------------------------------------+
//| Direction parity from deal history: direction of the LAST entry  |
//| deal of this EA. The next cycle trades the OPPOSITE side.        |
//+------------------------------------------------------------------+
long NextCycleDir()
  {
   // throttle: max one full-history scan per 2 s (flat-state retry ticks)
   static datetime lastScan = 0;
   static long     cached   = POSITION_TYPE_BUY;
   datetime now = TimeCurrent();
   if(lastScan != 0 && now - lastScan < 2)
      return(cached);
   lastScan = now;

   datetime from = now - 90 * 86400;
   if(!HistorySelect(from, TimeCurrent() + 60))
      return(POSITION_TYPE_BUY);
   long lastType = -1;
   datetime lastT = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0)
         continue;
      if(HistoryDealGetString(t, DEAL_SYMBOL) != _Symbol)
         continue;
      if(HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic)
         continue;
      if(HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;
      long dType = HistoryDealGetInteger(t, DEAL_TYPE);
      if(dType != DEAL_TYPE_BUY && dType != DEAL_TYPE_SELL)
         continue;
      datetime dT = (datetime)HistoryDealGetInteger(t, DEAL_TIME);
      if(dT > lastT)
        {
         lastT = dT;
         lastType = dType;
        }
     }
   if(lastType == DEAL_TYPE_BUY)
      cached = POSITION_TYPE_SELL;
   else if(lastType == DEAL_TYPE_SELL)
      cached = POSITION_TYPE_BUY;
   else
      cached = POSITION_TYPE_BUY;           // nothing in history: begin with BUY
   return(cached);
  }

//+------------------------------------------------------------------+
//| High-impact news calendar, refreshed hourly.                     |
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

bool DayBlocked()
  {
   if(g_pausedUntil == 0)
      return(false);
   if(TimeCurrent() >= g_pausedUntil)
     {
      g_pausedUntil = 0;
      Print(g_tag, " equity-stop pause lifted");
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Manage one side's basket. allowOpen=false -> escape-only.        |
//+------------------------------------------------------------------+
void RunBasket(long dir, double priceEsc, bool allowOpen)
  {
   double be = 0, adverse = 0;
   int n = CountSideAndBe(dir, be, adverse);
   if(n == 0)
      return;

   g_lastBasketTP = be + ((dir == POSITION_TYPE_BUY) ? g_tpd : -g_tpd);
   g_lastBasketN = n;
   g_lastBasketDir = dir;

   // escape: whole basket at breakeven + $1.80 (batch close, no server TP)
   double bucket = be + ((dir == POSITION_TYPE_BUY) ? g_tpd : -g_tpd);
   bool hit = (dir == POSITION_TYPE_BUY) ? (priceEsc >= bucket) : (priceEsc <= bucket);
   if(hit)
     {
      CloseAllSide(dir, "[tp " + DoubleToString(bucket, g_dig) + "]");
      return;
     }

   // layer trigger: $4.00 past the most adverse entry
   if(allowOpen && !NewsHold())
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
         if(OpenLayer(dir, nextLot))
            Print(g_tag, " layer ", n, " dir=",
                  (dir == POSITION_TYPE_BUY ? "BUY" : "SELL"), " lot=", nextLot);
        }
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;

   // equity guard takes priority over everything
   if(InpEquityStopMoney > 0)
     {
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq < bal - InpEquityStopMoney)
        {
         datetime now = TimeCurrent();
         g_pausedUntil = now - (now % 86400) + 86400;
         Print(g_tag, " EQUITY STOP: eq=", eq, " fell ", InpEquityStopMoney,
               " below balance; closing all, paused to next server day");
         CloseAllSide(POSITION_TYPE_BUY, "[eqstop]");
         CloseAllSide(POSITION_TYPE_SELL, "[eqstop]");
         return;
        }
     }

   double beB = 0, advB = 0, beS = 0, advS = 0;
   int nb = CountSideAndBe(POSITION_TYPE_BUY, beB, advB);
   int ns = CountSideAndBe(POSITION_TYPE_SELL, beS, advS);
   int total = nb + ns;

   if(DayBlocked())
     {
      Comment(g_tag, " paused (equity stop)");
      g_prevN = total;
      g_historyDirty = true;
      return;
     }

   if(total == 0)
     {
      g_lastBasketTP = 0.0;
      g_lastBasketN = 0;

      // flat: new cycle on the OPPOSITE side of the last entry deal
      if(g_prevN > 0 || g_historyDirty)
        {
         long dir = NextCycleDir();
         if(!NewsHold())
           {
            if(OpenLayer(dir, LayerVol(0)))
               g_historyDirty = false;      // retry every tick until the entry lands
           }
        }
      g_prevN = 0;
      Comment(g_tag, " ", InpMagic, "  flat, waiting cycle  L/S = 0/0");
      return;
     }

   // exactly one side should be live; if both are (leftover), manage both
   // escape-only and open nothing until one clears.
   g_prevN = total;
   if(nb > 0 && ns > 0)
     {
      RunBasket(POSITION_TYPE_BUY, bid, false);
      RunBasket(POSITION_TYPE_SELL, ask, false);
      Comment(g_tag, " ", InpMagic, "  two-sided leftover, escape-only  L/S = ",
              nb, "/", ns);
      return;
     }
   if(nb > 0)
      RunBasket(POSITION_TYPE_BUY, bid, true);
   else
      RunBasket(POSITION_TYPE_SELL, ask, true);

   // live basket escape level: show only the basket that is being managed
   string tpInfo = "";
   if(g_lastBasketDir == POSITION_TYPE_BUY && g_lastBasketN > 0)
      tpInfo = "  BUY-basket TP=" + DoubleToString(g_lastBasketTP, g_dig);
   else if(g_lastBasketDir == POSITION_TYPE_SELL && g_lastBasketN > 0)
      tpInfo = "  SELL-basket TP=" + DoubleToString(g_lastBasketTP, g_dig);

   Comment(g_tag, " ", InpMagic,
           "  L/S = ", nb, "/", ns,
           tpInfo,
           (g_newsHeld ? "  [news pause]" : ""));
  }
//+------------------------------------------------------------------+
