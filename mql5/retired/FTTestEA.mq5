//+------------------------------------------------------------------+
//| FTTestEA.mq5                                                       |
//| Forward-test EA: 7 strategies x fixed-SL / trailing-SL twins.     |
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
//|   london    London-open breakout of the Asian (overnight) range    |
//|   squeeze   Bollinger-in-Keltner squeeze -> expansion breakout     |
//|                                                                   |
//| Usage: attach to a chart per strategy. Give the fixed twin        |
//| magic 9300xx and the trailing twin magic 9400xx with the same     |
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
   FT_SMC      = 4, // smc: liquidity sweep + reversal candle
   FT_LONDON   = 5, // london: Asian-range breakout at London open
   FT_SQUEEZE  = 6, // squeeze: Bollinger-in-Keltner expansion
   FT_TRENDPULLBACK = 9, // trendpullback: H1 trend + M15 pullback
   FT_DONCHIAN = 10 // donchian: Donchian-20 on the H1 host chart
  };
input group             "Core"
input ENUM_FT_STRATEGY  InpStrategy     = FT_BREAKOUT; // Strategy
input ENUM_TIMEFRAMES   InpTimeframe    = PERIOD_M15;  // Signal timeframe
input double            InpLots         = 0.01;        // Lot size (fixed)
input int               InpMagic        = 0;           // Magic (9300xx fixed / 9400xx trailing; 0 = refuse)

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
// trailing-modify failure backoff (see TrailStop)
datetime g_lastTrailFail = 0;
// H1 context for FT_TRENDPULLBACK (real H1 feed, shift 1 = last closed bar)
MqlRates g_h1[];
int      g_h1n = 0;
datetime g_lastBar  = 0;
datetime g_lastArm  = 0;
// dual-stop (straddle/london) arming state -- mirrors the runner's _run_dual:
// state is derived from LIVE orders so failed sends retry every few seconds
// instead of waiting for the next period; one trade per period per twin.
datetime g_dualPeriod = 0;
bool     g_dualFired  = false;
bool     g_skipBuy    = false;
bool     g_skipSell   = false;

// London-open breakout session bounds in SERVER hours (Fusion server ~= UTC+3,
// so London open 08:00 UTC ~= 11:00 server). Asian range = same-day bars
// before LONDON_START_HOUR. Mirrors scripts/forward_test.py.
#define LONDON_START_HOUR 11
#define LONDON_END_HOUR   17

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
      case FT_LONDON:   return("london");
      case FT_SQUEEZE:  return("squeeze");
      case FT_TRENDPULLBACK: return("trendpullback");
      case FT_DONCHIAN:  return("donchian");
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
   if(InpMagic <= 0)
     {
      Print("REFUSING: InpMagic must be set explicitly (9300xx fixed / 9400xx ",
            "trailing). Load one of the FTTestEA_*.set presets.");
      return(INIT_FAILED);
     }
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
   // show the strategy name on the chart so each window is self-describing
   Comment(g_name, " ", IntegerToString(InpMagic), "  ", EnumToString(InpTimeframe),
           InpUseTrailing ? "  [trailing]" : "  [fixed]");
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

double CalcStdDev(const double &closes[], int period)
  {
   int bars = ArraySize(closes);
   if(bars < period)
      return(-1);
   double mid = 0.0;
   for(int i = bars - period; i < bars; i++)
      mid += closes[i];
   mid /= period;
   double var = 0.0;
   for(int i = bars - period; i < bars; i++)
      var += (closes[i] - mid) * (closes[i] - mid);
   return(MathSqrt(var / period));
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
      // t == 0 means the index was stale (OrdersTotal() and OrderGetTicket are
      // not atomic, and another EA on this account can delete a pending in
      // between). Without this guard OrderDelete(0) is sent and the real
      // pending is left behind -- see the identical comment in FTTestCore.mqh.
      if(t == 0)
         continue;
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

bool HasPendingSide(ENUM_ORDER_TYPE type)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE) == type)
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
//| TRENDPULLBACK: H1 trend (last closed H1 close vs EMA50 of the     |
//| real H1 feed fetched in OnTick) + M15 pullback to EMA(21) that    |
//| closes as a rejection candle in the trend direction.              |
//+------------------------------------------------------------------+
void SigTrendPullback(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 30 || a <= 0 || g_h1n < 60)
      return;
   double hc[];
   ArrayResize(hc, g_h1n);
   for(int i = 0; i < g_h1n; i++)
      hc[i] = g_h1[i].close;
   double trendEma = CalcEMA(hc, 50);
   if(trendEma < 0)
      return;
   bool up = (hc[g_h1n - 1] > trendEma);
   double closes[];
   ArrayResize(closes, bars);
   for(int i = 0; i < bars; i++)
      closes[i] = r[i].close;
   double e21 = CalcEMA(closes, 21);
   if(e21 < 0)
      return;
   MqlRates b = r[bars - 1];
   double px = b.close;
   if(up && b.low <= e21 && b.close > b.open)
      ActOnSignal(ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(!up && b.high >= e21 && b.close < b.open)
      ActOnSignal(ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

//+------------------------------------------------------------------+
//| DONCHIAN: Donchian-20 on the HOST chart (same engine as breakout) |
//+------------------------------------------------------------------+
void SigDonchian(const MqlRates &r[], double a)
  {
   SigBreakout(r, a);
  }

//+------------------------------------------------------------------+
//| Straddle: dual stop orders around the 4-bar range each hour       |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Dual-stop arming (straddle/london): period-scoped, retry-safe.    |
//+------------------------------------------------------------------+
void ArmDual(datetime period, bool haveLevels, double buy_stop, double sell_stop, double a)
  {
   if(period != g_dualPeriod)
     {
      g_dualPeriod = period;
      g_dualFired  = false;
      g_skipBuy    = false;
      g_skipSell   = false;
      DeleteMyPendings(); // new period: clear leftovers
     }
   if(FindPosition() != 0)
     {
      g_dualFired = true;
      DeleteMyPendings(); // one side filled -> kill the far one
      return;
     }
   if(g_dualFired)
      return; // already traded this period
   if(!haveLevels)
      return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // stops must sit on the correct side of the market or the broker rejects;
   // a failed send is retried on the next arm call (every few seconds)
   if(!HasPendingSide(ORDER_TYPE_BUY_STOP) && !g_skipBuy)
     {
      if(buy_stop > ask)
         trade.BuyStop(InpLots, buy_stop, _Symbol, buy_stop - a, buy_stop + a,
                       ORDER_TIME_GTC, 0, Label());
      else
        {
         Print(Label(), " skip buy stop (price already beyond range)");
         g_skipBuy = true;
        }
     }
   if(!HasPendingSide(ORDER_TYPE_SELL_STOP) && !g_skipSell)
     {
      if(sell_stop < bid)
         trade.SellStop(InpLots, sell_stop, _Symbol, sell_stop + a, sell_stop - a,
                        ORDER_TIME_GTC, 0, Label());
      else
        {
         Print(Label(), " skip sell stop (price already beyond range)");
         g_skipSell = true;
        }
     }
  }

void SigStraddle(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 6 || a <= 0)
      return;
   datetime hour = r[bars - 1].time - (r[bars - 1].time % 3600);
   double hi = r[bars - 4].high, lo = r[bars - 4].low;
   for(int i = bars - 3; i < bars; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   double buf = 0.25 * a;
   ArmDual(hour, true, hi + buf, lo - buf, a);
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
//| London: dual stop orders around the Asian range, once per day     |
//+------------------------------------------------------------------+
void SigLondon(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 30 || a <= 0)
      return;
   datetime day = r[bars - 1].time - (r[bars - 1].time % 86400);
   int hour = (int)((r[bars - 1].time % 86400) / 3600);
   bool haveLevels = false;
   double buy_stop = 0, sell_stop = 0;
   if(hour >= LONDON_START_HOUR && hour < LONDON_END_HOUR)
     {
      double hi = 0.0, lo = 0.0;
      int asian = 0;
      for(int i = 0; i < bars - 1; i++)
        {
         if(r[i].time < day)
            continue; // only today's pre-London bars form the Asian range
         if((int)((r[i].time % 86400) / 3600) >= LONDON_START_HOUR)
            continue;
         if(asian == 0) { hi = r[i].high; lo = r[i].low; }
         else { hi = MathMax(hi, r[i].high); lo = MathMin(lo, r[i].low); }
         asian++;
        }
      if(asian >= 4 && hi > lo)
        {
         double buf = 0.25 * a;
         buy_stop = hi + buf;
         sell_stop = lo - buf;
         haveLevels = true;
        }
     }
   // ArmDual resets state at the day boundary even without levels, so no
   // stale orders linger past their period
   ArmDual(day, haveLevels, buy_stop, sell_stop, a);
  }

//+------------------------------------------------------------------+
//| Squeeze: Bollinger(20,2) inside Keltner(20,1.5*ATR) on >=6 of    |
//| the prior 10 bars -> enter on the expansion close beyond the      |
//| Bollinger band. Keltner width uses the latest ATR for all checked |
//| bars (the Python twin mirrors this approximation exactly).        |
//+------------------------------------------------------------------+
void SigSqueeze(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 30 || a <= 0)
      return;
   double closes[];
   ArrayResize(closes, bars);
   for(int i = 0; i < bars; i++)
      closes[i] = r[i].close;
   int squeezed = 0;
   for(int idx = bars - 11; idx < bars - 1; idx++)
     {
      int n = idx + 1;
      double seg[];
      ArrayResize(seg, n);
      for(int i = 0; i < n; i++)
         seg[i] = closes[i];
      double sd = CalcStdDev(seg, 20);
      double e  = CalcEMA(seg, 20);
      if(sd < 0 || e < 0)
         continue;
      double mid = 0.0;
      for(int i = n - 20; i < n; i++)
         mid += closes[i];
      mid /= 20.0;
      if(mid + 2 * sd < e + 1.5 * a && mid - 2 * sd > e - 1.5 * a)
         squeezed++;
     }
   if(squeezed < 6)
      return;
   double sd = CalcStdDev(closes, 20);
   if(sd < 0)
      return;
   double mid = 0.0;
   for(int i = bars - 20; i < bars; i++)
      mid += closes[i];
   mid /= 20.0;
   double px = closes[bars - 1];
   if(px > mid + 2 * sd)
      ActOnSignal(ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(px < mid - 2 * sd)
      ActOnSignal(ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
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
   // hardening: honor BOTH broker distance limits. STOPS_LEVEL rejects new SLs
   // too close to price; FREEZE_LEVEL rejects modifies near a pending trigger /
   // existing SL. Ignoring either caused 'close to market' bursts under latency.
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_dist = MathMax((double)stops_level, (double)freeze_level) * _Point;
   // hardening: after a failed modify, back off 30 s before the next attempt so
   // a latency/timeout window cannot turn into a per-tick request storm.
   if(g_lastTrailFail > 0 && TimeCurrent() - g_lastTrailFail < 30)
      return;

   if(type == POSITION_TYPE_BUY)
     {
      double gain = bid - open;
      if(gain < InpTrailActAtr * g_atr)
         return;
      double new_sl = bid - InpTrailDistAtr * g_atr;
      if(new_sl > sl + InpTrailStepAtr * g_atr && new_sl < bid - min_dist)
        {
         if(trade.PositionModify(t, new_sl, tp))
           {
            g_lastTrailFail = 0;
            Print(Label(), " trail SL -> ", new_sl);
           }
         else
           {
            g_lastTrailFail = TimeCurrent();
            Print(Label(), " trail modify FAILED ret=", trade.ResultRetcode(),
                  " (", trade.ResultRetcodeDescription(), ") new_sl=", new_sl,
                  " sl=", sl, " bid=", bid, " -- retry in 30s");
           }
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
         if(trade.PositionModify(t, new_sl, tp))
           {
            g_lastTrailFail = 0;
            Print(Label(), " trail SL -> ", new_sl);
           }
         else
           {
            g_lastTrailFail = TimeCurrent();
            Print(Label(), " trail modify FAILED ret=", trade.ResultRetcode(),
                  " (", trade.ResultRetcodeDescription(), ") new_sl=", new_sl,
                  " sl=", sl, " ask=", ask, " -- retry in 30s");
           }
        }
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   TrailStop(); // runs every tick so trailing reacts to live price

   // dual-stop strategies arm/retry every few seconds (not just on new bars)
   // so a failed send is retried within the period
   if(InpStrategy == FT_STRADDLE || InpStrategy == FT_LONDON)
     {
      if(TimeCurrent() - g_lastArm < 5)
         return;
      g_lastArm = TimeCurrent();
      MqlRates dr[];
      if(ClosedBars(dr, 300) < 30)
         return;
      double da = CalcATR(dr, 14);
      if(da <= 0)
         return;
      g_atr = da; // keep trailing twins working
      if(InpStrategy == FT_STRADDLE)
         SigStraddle(dr, da);
      else
         SigLondon(dr, da);
      return;
     }

   MqlRates r[];
   if(ClosedBars(r, 300) < 30)
      return;
   if(r[ArraySize(r) - 1].time == g_lastBar)
      return; // wait for a new closed bar
   g_lastBar = r[ArraySize(r) - 1].time;
   g_atr = CalcATR(r, 14);
   if(g_atr <= 0)
      return;

   // FT_TRENDPULLBACK reads the REAL H1 feed for its trend leg
   if(InpStrategy == FT_TRENDPULLBACK)
     {
      g_h1n = CopyRates(_Symbol, PERIOD_H1, 1, 400, g_h1);
      if(g_h1n < 60)
         return;
     }

   switch(InpStrategy)
     {
      case FT_BREAKOUT: SigBreakout(r, g_atr); break;
      case FT_MEANREV:  SigMeanrev(r, g_atr);  break;
      case FT_MACROSS:  SigMacross(r, g_atr);  break;
      case FT_STRADDLE: SigStraddle(r, g_atr); break;
      case FT_SMC:      SigSMC(r, g_atr);      break;
      case FT_LONDON:   SigLondon(r, g_atr);   break;
      case FT_SQUEEZE:  SigSqueeze(r, g_atr);  break;
      case FT_TRENDPULLBACK: SigTrendPullback(r, g_atr); break;
      case FT_DONCHIAN:  SigDonchian(r, g_atr);  break;
     }
  }
//+------------------------------------------------------------------+
