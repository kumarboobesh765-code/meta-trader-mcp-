//+------------------------------------------------------------------+
//| FTTestEA.mq5                                                       |
//| Forward-test EA: 5 strategies x fixed-SL / trailing-SL twins.     |
//| Mirrors scripts/forward_test.py so results stay comparable.       |
//|                                                                   |
//| Strategies (same rules as the Python forward test):               |
//|   breakout  Donchian-20 breakout of prior-bar extremes            |
//|   meanrev   RSI(14) fade (<25 buy / >75 sell)                     |
//|   macross   EMA9/EMA21 cross                                      |
//|   straddle  dual stop orders around the 4-bar range each hour     |
//|   smc       liquidity sweep + reversal candle, 1:3 R:R            |
//|             (from the video: sweep of an N-bar extreme that       |
//|              closes back inside + doji/hammer confirmation)       |
//|                                                                   |
//| Usage: attach to a chart per strategy. Give the fixed twin        |
//| magic 9100xx and the trailing twin magic 9200xx with the same     |
//| strategy settings (InpUseTrailing=true) so pairs compare cleanly. |
//| Comments carry "<strategy> <magic>" for the MT5 Comment column.   |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#include <Trade\Trade.mqh>

enum ENUM_FT_STRATEGY
  {
   FT_BREAKOUT = 0, // breakout: Donchian-20
   FT_MEANREV  = 1, // meanrev: RSI(14) fade
   FT_MACROSS  = 2, // macross: EMA9/21 cross
   FT_STRADDLE = 3, // straddle: hourly dual stops
   FT_SMC      = 4  // smc: liquidity sweep + reversal candle
  };

input group             "Core"
input ENUM_FT_STRATEGY  InpStrategy     = FT_BREAKOUT; // Strategy
input ENUM_TIMEFRAMES   InpTimeframe    = PERIOD_M15;  // Signal timeframe
input double            InpLots         = 0.01;        // Lot size (fixed)
input int               InpMagic        = 910001;      // Magic number

input group             "Trailing SL (true for the -T twin)"
input bool              InpUseTrailing  = false;       // Use trailing SL
input double            InpTrailActAtr  = 1.0;         // Activate after (x ATR)
input double            InpTrailDistAtr = 1.2;         // Trail distance (x ATR)
input double            InpTrailStepAtr = 0.3;         // Min SL move (x ATR)

input group             "Safety"
input bool              InpAllowReal    = false;       // Allow REAL accounts
input int               InpDeviationPts = 50;          // Max slippage (points)

CTrade  trade;
string  g_name;
double  g_atr = 0;
datetime g_lastBar  = 0;
datetime g_lastHour = 0;

//+------------------------------------------------------------------+
string StratName(ENUM_FT_STRATEGY s)
  {
   switch(s)
     {
      case FT_BREAKOUT: return("breakout");
      case FT_MEANREV:  return("meanrev");
      case FT_MACROSS:  return("macross");
      case FT_STRADDLE: return("straddle");
      case FT_SMC:      return("smc");
     }
   return("unknown");
  }

string Label()
  {
   return(StringFormat("%s %d", g_name, InpMagic));
  }

//+------------------------------------------------------------------+
//| Safety rail: demo-only unless explicitly allowed                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_name = StratName(InpStrategy);
   ENUM_ACCOUNT_TRADE_MODE mode =
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_REAL && !InpAllowReal)
     {
      Print("REFUSING: real-money account and InpAllowReal=false. ",
            "This EA is demo-only unless you deliberately enable it.");
      return(INIT_FAILED);
     }
   trade.SetDeviationInPoints(InpDeviationPts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetExpertMagicNumber(InpMagic);
   Print(Label(), " started on ", _Symbol, " ", EnumToString(InpTimeframe),
         " lots=", InpLots, " trailing=", InpUseTrailing ? "ON" : "OFF");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Math helpers (closed bars only: r[0]=oldest ... r[n-1]=last)      |
//+------------------------------------------------------------------+
int ClosedBars(MqlRates &r[], int n)
  {
   return(CopyRates(_Symbol, InpTimeframe, 1, n, r));
  }

double CalcATR(const MqlRates &r[], int period)
  {
   int bars = ArraySize(r);
   if(bars < period + 1)
      return(0);
   double sum = 0.0;
   for(int i = bars - period; i < bars; i++)
     {
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low,
                 MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      sum += tr;
     }
   return(sum / period);
  }

double CalcRSI(const MqlRates &r[], int period)
  {
   int bars = ArraySize(r);
   if(bars < period + 2)
      return(-1);
   double ag = 0.0, al = 0.0;
   for(int i = 1; i <= period; i++)
     {
      double d = r[i].close - r[i - 1].close;
      ag += MathMax(d, 0.0);
      al += MathMax(-d, 0.0);
     }
   ag /= period;
   al /= period;
   for(int i = period + 1; i < bars; i++)
     {
      double d = r[i].close - r[i - 1].close;
      ag = (ag * (period - 1) + MathMax(d, 0.0)) / period;
      al = (al * (period - 1) + MathMax(-d, 0.0)) / period;
     }
   if(al == 0.0)
      return(100.0);
   return(100.0 - 100.0 / (1.0 + ag / al));
  }

double CalcEMA(const double &closes[], int period)
  {
   int bars = ArraySize(closes);
   if(bars < period)
      return(-1);
   double k = 2.0 / (period + 1), e = 0.0;
   for(int i = 0; i < period; i++)
      e += closes[i];
   e /= period;
   for(int i = period; i < bars; i++)
      e = closes[i] * k + e * (1 - k);
   return(e);
  }

//+------------------------------------------------------------------+
//| Position helpers                                                  |
//+------------------------------------------------------------------+
ulong FindPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      return(t);
     }
   return(0);
  }

bool OpenMarket(ENUM_ORDER_TYPE type, double sl, double tp)
  {
   double price = (type == ORDER_TYPE_BUY) ?
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool ok = trade.PositionOpen(_Symbol, type, InpLots, price, sl, tp, Label());
   Print(Label(), " OPEN ", (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
         " ", InpLots, " @ ", price, " sl=", sl, " tp=", tp, " ok=", ok,
         " ret=", trade.ResultRetcode());
   return(ok);
  }

void CloseMine()
  {
   ulong t = FindPosition();
   if(t != 0)
     {
      bool ok = trade.PositionClose(t);
      Print(Label(), " CLOSE #", t, " ok=", ok, " ret=", trade.ResultRetcode());
     }
  }

void DeleteMyPendings()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      trade.OrderDelete(t);
     }
  }

bool HasPending()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Signal-mode strategies: hold if aligned, reverse if opposed       |
//+------------------------------------------------------------------+
void ActOnSignal(ENUM_ORDER_TYPE type, double sl, double tp)
  {
   ulong t = FindPosition();
   if(t != 0)
     {
      long ptype = PositionGetInteger(POSITION_TYPE);
      if((type == ORDER_TYPE_BUY && ptype == POSITION_TYPE_BUY) ||
         (type == ORDER_TYPE_SELL && ptype == POSITION_TYPE_SELL))
         return; // already aligned, hold
      CloseMine(); // opposite signal -> reverse
     }
   OpenMarket(type, sl, tp);
  }

//+------------------------------------------------------------------+
//| Signals (mirroring scripts/forward_test.py)                       |
//+------------------------------------------------------------------+
void SigBreakout(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 25 || a <= 0)
      return;
   double hi = r[bars - 21].high, lo = r[bars - 21].low;
   for(int i = bars - 20; i < bars - 1; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   double close = r[bars - 1].close;
   if(close > hi)
      ActOnSignal(ORDER_TYPE_BUY, close - 2 * a, close + 3 * a);
   else if(close < lo)
      ActOnSignal(ORDER_TYPE_SELL, close + 2 * a, close - 3 * a);
  }

void SigMeanrev(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 20 || a <= 0)
      return;
   double rs = CalcRSI(r, 14);
   if(rs < 0)
      return;
   double px = r[bars - 1].close;
   if(rs < 25)
      ActOnSignal(ORDER_TYPE_BUY, px - 1.5 * a, px + 1.0 * a);
   else if(rs > 75)
      ActOnSignal(ORDER_TYPE_SELL, px + 1.5 * a, px - 1.0 * a);
  }

void SigMacross(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 62 || a <= 0)
      return;
   double closes[];
   ArrayResize(closes, bars);
   for(int i = 0; i < bars; i++)
      closes[i] = r[i].close;
   double f  = CalcEMA(closes, 9),  s  = CalcEMA(closes, 21);
   int n = bars - 1;
   double c2[];
   ArrayResize(c2, n);
   for(int i = 0; i < n; i++)
      c2[i] = closes[i];
   double fp = CalcEMA(c2, 9), sp = CalcEMA(c2, 21);
   if(f < 0 || s < 0 || fp < 0 || sp < 0)
      return;
   double px = closes[bars - 1];
   if(fp <= sp && f > s)
      ActOnSignal(ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(fp >= sp && f < s)
      ActOnSignal(ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

//+------------------------------------------------------------------+
//| Straddle: dual stop orders around the 4-bar range each hour       |
//+------------------------------------------------------------------+
void SigStraddle(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 6 || a <= 0)
      return;
   datetime hour = r[bars - 1].time - (r[bars - 1].time % 3600);
   if(hour == g_lastHour)
      return;
   g_lastHour = hour;
   DeleteMyPendings();
   if(FindPosition() != 0)
      return; // still in a trade from last hour
   double hi = r[bars - 4].high, lo = r[bars - 4].low;
   for(int i = bars - 3; i < bars; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   double buf = 0.25 * a;
   double buy_stop  = hi + buf;
   double sell_stop = lo - buf;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // stops must sit on the correct side of the market or the broker rejects
   if(buy_stop > ask)
      trade.BuyStop(InpLots, buy_stop, _Symbol, buy_stop - a, buy_stop + a,
                    ORDER_TIME_GTC, 0, Label());
   else
      Print(Label(), " skip buy stop (price already above range)");
   if(sell_stop < bid)
      trade.SellStop(InpLots, sell_stop, _Symbol, sell_stop + a, sell_stop - a,
                     ORDER_TIME_GTC, 0, Label());
   else
      Print(Label(), " skip sell stop (price already below range)");
  }

//+------------------------------------------------------------------+
//| SMC: liquidity sweep + reversal candle, 1:3 R:R                   |
//| sweep: last closed bar wicks beyond the prior 20-bar extreme but  |
//| closes back inside; confirmation: small body (doji/hammer) with   |
//| the rejection wick on the sweep side. SL beyond the wick,         |
//| TP = 3x risk (the video's ~1:3 R:R).                              |
//+------------------------------------------------------------------+
void SigSMC(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 25 || a <= 0)
      return;
   double hi = r[bars - 22].high, lo = r[bars - 22].low;
   for(int i = bars - 21; i < bars - 1; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   MqlRates b = r[bars - 1];
   double range = b.high - b.low;
   if(range <= 0)
      return;
   double body = MathAbs(b.close - b.open);
   double body_ratio = body / range;
   double lower_wick = MathMin(b.open, b.close) - b.low;
   double upper_wick = b.high - MathMax(b.open, b.close);
   bool small_body = (body_ratio <= 0.30) || (body_ratio <= 0.45 && (lower_wick > 2 * body || upper_wick > 2 * body));

   // bullish sweep: dip below prior low, close back above + hammer/doji
   if(b.low < lo && b.close > lo && small_body && lower_wick > 0.5 * range)
     {
      double entry = b.close;
      double sl = b.low - 0.1 * a;
      double risk = entry - sl;
      if(risk > 0)
         ActOnSignal(ORDER_TYPE_BUY, sl, entry + 3 * risk);
      return;
     }
   // bearish sweep: spike above prior high, close back below + rejection
   if(b.high > hi && b.close < hi && small_body && upper_wick > 0.5 * range)
     {
      double entry = b.close;
      double sl = b.high + 0.1 * a;
      double risk = sl - entry;
      if(risk > 0)
         ActOnSignal(ORDER_TYPE_SELL, sl, entry - 3 * risk);
     }
  }

//+------------------------------------------------------------------+
//| Trailing SL twin: trail once InpTrailActAtr in profit             |
//+------------------------------------------------------------------+
void TrailStop()
  {
   if(!InpUseTrailing || g_atr <= 0)
      return;
   ulong t = FindPosition();
   if(t == 0)
      return;
   double open = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl   = PositionGetDouble(POSITION_SL);
   double tp   = PositionGetDouble(POSITION_TP);
   long   type = PositionGetInteger(POSITION_TYPE);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = stops_level * _Point;

   if(type == POSITION_TYPE_BUY)
     {
      double gain = bid - open;
      if(gain < InpTrailActAtr * g_atr)
         return;
      double new_sl = bid - InpTrailDistAtr * g_atr;
      if(new_sl > sl + InpTrailStepAtr * g_atr && new_sl < bid - min_dist)
        {
         trade.PositionModify(t, new_sl, tp);
         Print(Label(), " trail SL -> ", new_sl);
        }
     }
   else
     {
      double gain = open - ask;
      if(gain < InpTrailActAtr * g_atr)
         return;
      double new_sl = ask + InpTrailDistAtr * g_atr;
      if((sl == 0 || new_sl < sl - InpTrailStepAtr * g_atr) && new_sl > ask + min_dist)
        {
         trade.PositionModify(t, new_sl, tp);
         Print(Label(), " trail SL -> ", new_sl);
        }
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   TrailStop(); // runs every tick so trailing reacts to live price

   MqlRates r[];
   if(ClosedBars(r, 300) < 30)
      return;
   if(r[ArraySize(r) - 1].time == g_lastBar)
      return; // wait for a new closed bar
   g_lastBar = r[ArraySize(r) - 1].time;
   g_atr = CalcATR(r, 14);
   if(g_atr <= 0)
      return;

   switch(InpStrategy)
     {
      case FT_BREAKOUT: SigBreakout(r, g_atr); break;
      case FT_MEANREV:  SigMeanrev(r, g_atr);  break;
      case FT_MACROSS:  SigMacross(r, g_atr);  break;
      case FT_STRADDLE: SigStraddle(r, g_atr); break;
      case FT_SMC:      SigSMC(r, g_atr);      break;
     }
  }
//+------------------------------------------------------------------+
