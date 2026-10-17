//+------------------------------------------------------------------+
//| FTTestCore.mqh - shared engine for the per-strategy FTTest EAs.   |
//| Each FTTest_<strategy>.mq5 defines EA_STRATEGY + EA_TITLE and     |
//| includes this file, so every EA build is NAMED after its strategy |
//| (visible in the chart's expert list, journal and comments).       |
//| Logic mirrors scripts/forward_test.py exactly.                    |
//+------------------------------------------------------------------+
#ifndef __FTTEST_CORE_MQH__
#define __FTTEST_CORE_MQH__

#include <Trade\Trade.mqh>

#ifndef EA_STRATEGY
#define EA_STRATEGY FT_BREAKOUT
#endif
#ifndef EA_TITLE
#define EA_TITLE "breakout"
#endif

enum ENUM_FT_STRATEGY
  {
   FT_BREAKOUT = 0, // breakout: Donchian-20
   FT_MEANREV  = 1, // meanrev: RSI(14) fade
   FT_MACROSS  = 2, // macross: EMA9/21 cross
   FT_STRADDLE = 3, // straddle: hourly dual stops
   FT_SMC      = 4, // smc: liquidity sweep + reversal candle
   FT_LONDON   = 5, // london: Asian-range breakout at London open
   FT_SQUEEZE  = 6, // squeeze: Bollinger-in-Keltner expansion
   FT_PROFILE  = 7, // profile: TPO value-area rotation + breakout
   FT_ORDERFLOW = 8, // orderflow: delta imbalance + absorption
   FT_TRENDPULLBACK = 9, // trendpullback: H1 trend + M15 EMA(21) pullback
   FT_DONCHIAN = 10, // donchian: Donchian-20 on the H1 host chart
   FT_TREND = 11, // trend: H1 EMA50 trend + H1 EMA9/21 momentum
   FT_SUPRES = 12, // supres: S/R window rejection bounce
   FT_SUPERTREND = 13, // supertrend: Pine ta.supertrend flip (RMA ATR)
   FT_LIQUIDITYSWEEP = 14, // liquiditysweep: H4 sweep-and-reclaim limit entries
   FT_FIXFADE = 15, // fixfade: fade the 13-14 UTC pre-London-Fix impulse (M15)
   FT_VWAPREV = 16, // vwaprev: session-VWAP band reversion (M15, London anchor)
   FT_DAYOPEN = 17, // dayopen: weekday server-day-open long (22:00 UTC drift)
   FT_SWING = 18, // swing: H1 structure bias + M15/M30 EMA21 pullback rejection
   FT_SWEEPABS = 19 // sweepabs: M15 sweep + volume absorption, market entry
  };

input group             "Core"
input ENUM_TIMEFRAMES   InpTimeframe    = PERIOD_M15;  // Signal timeframe
input double            InpLots         = 0.01;        // Lot size (fixed)
input int               InpMagic        = 0;           // Magic (9300xx fixed / 9400xx trailing; 0 = refuse)

input group             "Trailing SL (true for the -T twin)"
input bool              InpUseTrailing  = false;       // Use trailing SL
input double            InpTrailActAtr  = 1.0;         // Activate after (x ATR)
input double            InpTrailDistAtr = 1.2;         // Trail distance (x ATR)
input double            InpTrailStepAtr = 0.3;         // Min SL move (x ATR)

input group             "Liquidity Sweep (FT_LIQUIDITYSWEEP)"
input int               InpLSLookback   = 48;    // Sweep window (bars)
input double            InpLSWickRatio  = 0.20;  // Min wick share of range
input double            InpLSBufAtr     = 0.05;  // Reclaim buffer (x ATR)

input group             "Fix Fade (FT_FIXFADE) -- backtest 90d +$140 PF 6.2"
input double            InpFFImpulseAtr = 0.5;   // Min 13-14 UTC impulse (x ATR)
input double            InpFFSLBufAtr   = 0.3;   // SL buffer beyond impulse (x ATR)
input int               InpFFTimeStop   = 8;     // Time stop (bars)

input group             "VWAP Reversion (FT_VWAPREV) -- backtest 90d +$95"
input double            InpVRBandSigma  = 1.5;   // Entry band (sigma)
input int               InpVRMaxPerDay  = 2;     // Max entries per session
input int               InpVRTimeStop   = 16;    // Time stop (bars)

input group             "Sweep Absorption (FT_SWEEPABS) -- backtest 200d trail +$1087"
input int               InpSALookback   = 20;    // Sweep window (bars, excl. signal bar)
input double            InpSAWickRatio  = 0.20;  // Min wick-to-close share of range
input int               InpSATimeStop   = 96;    // Time stop (bars, 24h on M15)

input group             "Day Open (FT_DAYOPEN) -- backtest 180d +$796 PF 1.40"
input double            InpDOSLAtr      = 2.0;   // Stop loss (x ATR96)
input int               InpDOTimeStop   = 16;    // Time stop (bars)
input int               InpDOGapSkipMin = 180;   // Skip if session gap > (min) -- Monday

input group             "Market Profile (FT_PROFILE)"
input int               InpProfileBars   = 96;   // Profile lookback (bars)
input int               InpProfileBins   = 24;   // Price bins
input double            InpValueAreaPct  = 70.0; // Value area (% of TPOs)

input group             "Order Flow (FT_ORDERFLOW)"
input int               InpOFBars        = 30;   // Tick-flow window (minutes)
input double            InpOFImbRatio    = 3.0;  // Delta imbalance ratio
input double            InpOFMinCum      = 0.6;  // Min cumulative-delta share

input group             "Safety"
input bool              InpAllowReal    = false;       // Allow REAL accounts
input int               InpDeviationPts = 50;          // Max slippage (points)

CTrade  trade;
string  g_name = EA_TITLE;
double  g_atr = 0;
// trailing-modify failure backoff (see TrailStop)
datetime g_lastTrailFail = 0;
// (stuck-stop guard lives right above OnTick: pulses SL/TP when the server
//  leaves price through an unexecuted stop)
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
string Label()
  {
   return(StringFormat("%s %d", g_name, InpMagic));
  }

//+------------------------------------------------------------------+
//| Safety rail: demo-only unless explicitly allowed                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpMagic <= 0)
     {
      Print("REFUSING: InpMagic must be set explicitly (9300xx fixed / 9400xx ",
            "trailing). Load one of the FTTest preset .set files.");
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
   Print(EA_TITLE, " ", InpMagic, " started on ", _Symbol, " ",
         EnumToString(InpTimeframe), " lots=", InpLots,
         " trailing=", InpUseTrailing ? "ON" : "OFF");
   // show the strategy name on the chart so each window is self-describing
   Comment(EA_TITLE, " ", IntegerToString(InpMagic), "  ",
           EnumToString(InpTimeframe),
           InpUseTrailing ? "  [trailing]" : "  [fixed]");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   Comment("");
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
      // OrderGetTicket returns 0 when the index is stale -- OrdersTotal() and
      // the ticket lookup are not atomic, and another EA on this account can
      // delete a pending between the two calls, shifting every higher index
      // down by one. The two filters below then read whatever order was still
      // cached from the previous iteration, which for this EA is XAUUSD with
      // InpMagic, so the stale index passed both guards and OrderDelete(0) was
      // issued ("cancel #0 [invalid request]"). The real pending at that index
      // was left behind -- exactly the leftover straddle/london order this
      // function exists to clear.
      if(t == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      trade.OrderDelete(t);
     }
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
//| TPO market profile: body-time-at-price histogram over the lookback.
//| Each bar contributes 1 TPO per bin its body overlaps (a doji counts
//| one bin). POC = heaviest bin; the value area expands from the POC
//| until it covers InpValueAreaPct of all TPOs. Returns false when the
//| profile is degenerate (flat range, empty bins).
//+------------------------------------------------------------------+
bool MarketProfile(const MqlRates &r[], int bins, double &poc, double &vah, double &val)
  {
   int bars = ArraySize(r);
   if(bars < 20 || bins < 4)
      return(false);
   double lo = r[0].low, hi = r[0].high;
   for(int i = 1; i < bars; i++)
     {
      lo = MathMin(lo, r[i].low);
      hi = MathMax(hi, r[i].high);
     }
   if(hi <= lo)
      return(false);
   double step = (hi - lo) / bins;
   int tpo[];
   ArrayResize(tpo, bins);
   ArrayInitialize(tpo, 0);
   for(int i = 0; i < bars; i++)
     {
      double bl = MathMin(r[i].open, r[i].close);   // bar body = time at price
      double bh = MathMax(r[i].open, r[i].close);
      if(bh <= bl)
         bh = bl + step;                            // doji: count one bin
      int b0 = (int)MathFloor((bl - lo) / step);
      int b1 = (int)MathFloor((bh - lo) / step);
      if(b1 < b0) { int t = b0; b0 = b1; b1 = t; }
      for(int b = MathMax(b0, 0); b <= MathMin(b1, bins - 1); b++)
         tpo[b]++;
     }
   int total = 0, pocI = 0;
   for(int b = 0; b < bins; b++)
     {
      total += tpo[b];
      if(tpo[b] > tpo[pocI])
         pocI = b;
     }
   if(total <= 0 || tpo[pocI] <= 0)
      return(false);
   double need = total * InpValueAreaPct / 100.0;
   int loI = pocI, hiI = pocI;
   int covered = tpo[pocI];
   while(covered < need && (loI > 0 || hiI < bins - 1))
     {
      int dn = (loI > 0) ? tpo[loI - 1] : -1;        // candidate bin below
      int up = (hiI < bins - 1) ? tpo[hiI + 1] : -1; // candidate bin above
      if(dn < 0 && up < 0)
         break;
      if(up >= dn) { hiI++; covered += up; }
      else         { loI--; covered += dn; }
     }
   poc = lo + (pocI + 0.5) * step;
   vah = lo + (hiI + 1.0) * step;
   val = lo + loI * step;
   return(vah > val);
  }

//+------------------------------------------------------------------+
//| TRENDPULLBACK: H1 trend (last closed H1 close above/below EMA50   |
//| of the real H1 feed, fetched in OnTick into g_h1) + M15 pullback  |
//| to EMA(21) that closes as a rejection candle in the trend         |
//| direction. Matches the backtest (backtest_new_candidates.py),     |
//| which evaluated the trend on the true H1 series.                  |
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
   bool up = (hc[g_h1n - 1] > trendEma);   // last closed H1 close vs its EMA50
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
//| SigSwing: swing pullback in the direction of H1 structure.        |
//|                                                                   |
//| Deliberately NOT another "follow the flip" system: `trend`        |
//| (-$383 both arms) and `supertrend` (-$103 both arms) were retired |
//| 2026-10-05 precisely because they give back open profit in        |
//| XAUUSD's 1-2 ATR noise. This one targets that failure mode with  |
//| a WIDE 2.5 ATR stop and a 4 ATR target so the leg can run, then   |
//| leans on the trailing twin to harvest the run.                    |
//|                                                                   |
//|   bias    : last CLOSED H1 close vs EMA50 of H1 closes            |
//|   entry   : signal bar touches EMA21 and closes as a rejection    |
//|             candle in the bias direction                         |
//|   confirm : RSI(14) agrees with the direction (>=50 / <=50)       |
//|                                                                   |
//| Backtest scripts/backtest_swing.py + backtest_swing_walkforward.py|
//| (2026-10-05, 593d span, 30d windows rolled every 10d):           |
//|   M15  52/52 windows profitable, tight-trail +15016.71           |
//|   M30  52/52 windows profitable, tight-trail +10125.12           |
//|   H1   49/52 -- DECAYS, so H1 is NOT deployed.                    |
//| Fixed loses to trailing on every timeframe, matching the pattern |
//| seen across the rest of the rig.                                  |
//+------------------------------------------------------------------+
void SigSwing(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 30 || a <= 0 || g_h1n < 60)
      return;
   // --- bias leg: H1 structure from the REAL H1 feed
   double hc[];
   ArrayResize(hc, g_h1n);
   for(int i = 0; i < g_h1n; i++)
      hc[i] = g_h1[i].close;
   double e50 = CalcEMA(hc, 50);
   if(e50 < 0)
      return;
   bool up = (hc[g_h1n - 1] > e50);
   // --- pullback + rejection on the signal timeframe
   double closes[];
   ArrayResize(closes, bars);
   for(int i = 0; i < bars; i++)
      closes[i] = r[i].close;
   double e21 = CalcEMA(closes, 21);
   if(e21 < 0)
      return;
   // CalcRSI takes the RATES array (it reads .close internally); CalcEMA takes
// the extracted closes. Passing `closes` here is a type error (error 246).
   double rs = CalcRSI(r, 14);
   if(rs < 0)
      return;
   MqlRates b = r[bars - 1];
   double px = b.close;
   if(up && b.low <= e21 && b.close > b.open && rs >= 50.0)
      ActOnSignal(ORDER_TYPE_BUY, px - 2.5 * a, px + 4.0 * a);
   else if(!up && b.high >= e21 && b.close < b.open && rs <= 50.0)
      ActOnSignal(ORDER_TYPE_SELL, px + 2.5 * a, px - 4.0 * a);
  }

//+------------------------------------------------------------------+
//| DONCHIAN: Donchian-20 channel breakout on the HOST chart.         |
//| Identical engine to breakout -- the H1 host chart supplies the    |
//| higher timeframe (charts run FTTest_donchian on XAUUSD H1).       |
//+------------------------------------------------------------------+
void SigDonchian(const MqlRates &r[], double a)
  {
   SigBreakout(r, a);
  }

//+------------------------------------------------------------------+
//| TREND: H1 EMA50 trend leg + H1 EMA9/21 momentum leg, both on the  |
//| H1 host chart (every closed bar IS an H1 bucket). Long only when  |
//| both legs align up, short only when both align down; state-based  |
//| hold/reverse via ActOnSignal. Mirrors strat_trend exactly.        |
//+------------------------------------------------------------------+
void SigTrend(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 62 || a <= 0)
      return;
   double hc[];
   ArrayResize(hc, bars);
   for(int i = 0; i < bars; i++)
      hc[i] = r[i].close;
   double trendEma = CalcEMA(hc, 50);
   if(trendEma < 0)
      return;
   bool up = (hc[bars - 1] > trendEma);
   int n = MathMin(bars, 120);
   double win[];
   ArrayResize(win, n);
   for(int i = 0; i < n; i++)
      win[i] = hc[bars - n + i];
   double f9 = CalcEMA(win, 9), s21 = CalcEMA(win, 21);
   if(f9 < 0 || s21 < 0)
      return;
   double px = hc[bars - 1];
   if(up && f9 > s21)
      ActOnSignal(ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(!up && f9 < s21)
      ActOnSignal(ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

//+------------------------------------------------------------------+
//| SUPRES: support/resistance rejection bounce on the host chart.    |
//| S/R = the 200-bar window high/low. Short when the bar's high      |
//| probes within 0.25 ATR of resistance but the body closes back     |
//| below it as a bearish candle; long mirrored at support. SL 1.5    |
//| ATR beyond the close / TP 2.5 ATR (faster reversion-style exit).  |
//+------------------------------------------------------------------+
void SigSupRes(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 202 || a <= 0)
      return;
   int win = 200;
   double hi = r[bars - win - 1].high, lo = r[bars - win - 1].low;
   for(int i = bars - win; i < bars - 1; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   MqlRates b = r[bars - 1];
   double px = b.close;
   double near = 0.25 * a;
   bool at_res = (hi - b.high) <= near && b.close < hi - near && b.close < b.open;
   bool at_sup = (b.low - lo) <= near && b.close > lo + near && b.close > b.open;
   if(at_res)
      ActOnSignal(ORDER_TYPE_SELL, px + 1.5 * a, px - 2.5 * a);
   else if(at_sup)
      ActOnSignal(ORDER_TYPE_BUY, px - 1.5 * a, px + 2.5 * a);
  }

//+------------------------------------------------------------------+
//| PROFILE: breakout beyond the value area edge (+/- half ATR buffer)
//| or rotation from just outside an extreme back to the POC.
//+------------------------------------------------------------------+
void SigProfile(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 20 || a <= 0)
      return;
   // profile window = the LAST InpProfileBars closed bars (OnTick hands us
   // up to 300; slice so the profile spans exactly the configured lookback)
   int n = MathMin(bars, InpProfileBars);
   MqlRates sub[];
   ArrayResize(sub, n);
   for(int i = 0; i < n; i++)
      sub[i] = r[bars - n + i];
   double poc, vah, val;
   if(!MarketProfile(sub, InpProfileBins, poc, vah, val))
      return;
   double c = sub[n - 1].close;
   if(c > vah + 0.5 * a)          // breakout up: ride value migration
      ActOnSignal(ORDER_TYPE_BUY, c - 1.5 * a, c + 3.0 * a);
   else if(c < val - 0.5 * a)     // breakout down
      ActOnSignal(ORDER_TYPE_SELL, c + 1.5 * a, c - 3.0 * a);
   else if(c > vah)               // rotation: fade back toward the POC
      ActOnSignal(ORDER_TYPE_SELL, c + 1.2 * a, poc);
   else if(c < val)               // rotation: fade back toward the POC
      ActOnSignal(ORDER_TYPE_BUY, c - 1.2 * a, poc);
  }

//+------------------------------------------------------------------+
//| ORDER FLOW: per-minute signed delta from tick data. Exchange-style
//| feeds carry TICK_FLAG_BUY/SELL; retail CFD feeds usually do not, so
//| fall back to the classic tick rule (uptick = buy, downtick = sell).
//| Entries: (1) absorption -- a wide bar whose wick rejects the move
//| while cumulative flow agrees, (2) delta imbalance -- this closed
//| minute's delta overwhelms the previous one by InpOFImbRatio with
//| cumulative flow aligned, gated by InpOFMinCum of total flow.
//| Runs on the M1 chart series (chart timeframe = M1).
//+------------------------------------------------------------------+
void SigOrderflow(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < InpOFBars + 2 || a <= 0)
      return;
   MqlTick ticks[];
   int n = CopyTicks(_Symbol, ticks, COPY_TICKS_TRADE, 0, InpOFBars * 400);
   if(n < 100)
      return;
   int last = bars - 1;
   datetime bEnd = r[last].time;   // anchor buckets at the last CLOSED minute
   double delta[];
   ArrayResize(delta, InpOFBars);
   ArrayInitialize(delta, 0.0);
   long prevBid = 0, prevAsk = 0;
   int dir = 0, used = 0;
   for(int i = 0; i < n; i++)
     {
      datetime bt = (datetime)(ticks[i].time_msc / 1000);
      int b = (int)((bEnd - bt) / 60);
      if(b < 0 || b >= InpOFBars)
         continue;                       // newer than the closed bar / too old
      double v = (ticks[i].volume > 0) ? (double)ticks[i].volume : 1.0;
      double sv = 0.0;
      if((ticks[i].flags & TICK_FLAG_BUY) != 0)
         sv = v;
      else if((ticks[i].flags & TICK_FLAG_SELL) != 0)
         sv = -v;
      else
        {
         if(prevBid > 0)
           {
            if(ticks[i].bid > prevBid)      { sv = v;  dir = 1;  }
            else if(ticks[i].bid < prevBid) { sv = -v; dir = -1; }
            else if(ticks[i].ask > prevAsk) { sv = v;  dir = 1;  }
            else if(ticks[i].ask < prevAsk) { sv = -v; dir = -1; }
            else                             sv = v * dir;    // carry last dir
           }
         prevBid = (long)ticks[i].bid;
         prevAsk = (long)ticks[i].ask;
        }
      delta[b] += sv;
      used++;
     }
   if(used < 100)
      return;
   double cum = 0.0, absSum = 0.0;
   for(int b = 0; b < InpOFBars; b++)
     {
      cum += delta[b];
      absSum += MathAbs(delta[b]);
     }
   if(absSum <= 0)
      return;

   MqlRates bar = r[last];
   double range = bar.high - bar.low;
   double body = MathAbs(bar.close - bar.open);
   double lowerWick = MathMin(bar.open, bar.close) - bar.low;
   double upperWick = bar.high - MathMax(bar.open, bar.close);
   bool wideBar = (range > 0.8 * a);
   double c = bar.close;
   // absorption: the move was absorbed -- wide bar, long wick against it,
   // close back in the rejection direction, cumulative flow agrees
   bool absorbLong  = wideBar && lowerWick > 2.0 * body &&
                      c >= bar.low + 2.0 * range / 3.0 && cum >= 0;
   bool absorbShort = wideBar && upperWick > 2.0 * body &&
                      c <= bar.low + range / 3.0 && cum <= 0;
   if(absorbLong)
     {
      double sl = bar.low - 0.2 * a;
      ActOnSignal(ORDER_TYPE_BUY, sl, c + 2.0 * (c - sl));
     }
   else if(absorbShort)
     {
      double sl = bar.high + 0.2 * a;
      ActOnSignal(ORDER_TYPE_SELL, sl, c - 2.0 * (sl - c));
     }
   else
     {
      double d0 = delta[0], d1 = delta[1];   // closed minute vs the one before
      double share = MathAbs(cum) / absSum;
      if(d0 >= InpOFImbRatio * MathAbs(d1) && d1 < 0 &&
          cum > 0 && share >= InpOFMinCum)
         ActOnSignal(ORDER_TYPE_BUY, c - 1.0 * a, c + 2.0 * a);
      else if(-d0 >= InpOFImbRatio * MathAbs(d1) && d1 > 0 &&
              cum < 0 && share >= InpOFMinCum)
         ActOnSignal(ORDER_TYPE_SELL, c + 1.0 * a, c - 2.0 * a);
     }
  }

//+------------------------------------------------------------------+
//| Supertrend (Pine ta.supertrend port, faithful). Self-contained:   |
//| Wilder RMA ATR seeded with the first-bar TR, bands from (H+L)/2   |
//| +- factor*ATR, ratcheted against the previous FINAL band and reset |
//| when the PREV bar closed through it. Direction flips ONLY on a    |
//| close through the ratcheted band matching the CURRENT state's own |
//| band (downtrend state = upper band, uptrend state = lower band) -- |
//| flipping on the FRESH band is what froze the broken first port.   |
//| Convention: dir -1 = uptrend, +1 = downtrend (Pine). Faithful to  |
//| scripts/backtest_supertrend.py st_dir_pine() exactly.             |
//+------------------------------------------------------------------+
void CalcSupertrendFT(const MqlRates &r[], int period, double factor, int &dir[])
  {
   int n = ArraySize(r);
   ArrayResize(dir, n);
   double tr[], atr[];
   ArrayResize(tr, n);  ArrayResize(atr, n);
   for(int i = 0; i < n; i++)
     {
      if(i == 0)
         tr[i] = r[i].high - r[i].low;
      else
        {
         double pc = r[i - 1].close;
         tr[i] = MathMax(r[i].high - r[i].low,
                MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
        }
     }
   // Wilder RMA seeded with the SMA of the first `period` TRs (parity with
   // the backtest rma(); a first-bar-TR seed diverges for thousands of bars)
   int p = MathMin(period, n);
   double seed = 0.0;
   for(int i = 0; i < p; i++)
      seed += tr[i];
   seed /= p;
   for(int i = 0; i < n; i++)
      atr[i] = (i < period) ? seed : (atr[i - 1] * (period - 1) + tr[i]) / period;

   double ub[], lb[];
   ArrayResize(ub, n);  ArrayResize(lb, n);
   for(int i = 0; i < n; i++)
     {
      double src = (r[i].high + r[i].low) / 2.0;
      double up  = src + factor * atr[i];
      double dn  = src - factor * atr[i];
      if(i == 0)
        {
         ub[i] = up; lb[i] = dn; dir[i] = 1;   // start downtrend (Pine default)
         continue;
        }
      double plb = lb[i - 1], pub = ub[i - 1];
      lb[i] = (dn > plb || r[i - 1].close < plb) ? dn : plb;
      ub[i] = (up < pub || r[i - 1].close > pub) ? up : pub;
      if(dir[i - 1] == 1)                       // downtrend: st == upper band
         dir[i] = (r[i].close > ub[i]) ? -1 : 1;
      else                                      // uptrend: st == lower band
         dir[i] = (r[i].close < lb[i]) ? 1 : -1;
     }
  }

void SigSupertrend(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 60 || a <= 0)
      return;
   int dir[];
   CalcSupertrendFT(r, 5, 2.0, dir);  // 2026-09-30 corrected sweep: 90d H1
                                      // fixed +$304 PF 1.50 / trail +$255 PF 1.51
   int last = bars - 1;
   if(dir[last] == dir[last - 1])
      return;                       // no flip on this closed bar
   double px = r[last].close;
   if(dir[last] == -1)              // flip to uptrend -> buy
      ActOnSignal(ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else                             // flip to downtrend -> sell
      ActOnSignal(ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

//+------------------------------------------------------------------+
//| LIQUIDITYSWEEP: H4 sweep-and-reclaim with LIMIT entries at the    |
//| swept level (A/B partner of the user's compiled LiquiditySweepH4).|
//| Bullish: bar wicks BELOW the InpLSLookback-window low (wick >=    |
//| InpLSWickRatio of the range) and CLOSES back above it + buffer -> |
//| buy limit at the swept low. Bearish mirrored at the high. SL 1.5  |
//| ATR / TP 3 ATR from the limit price; one trade per signal bar;    |
//| pending is re-placed until filled or the next signal replaces it. |
//| Params from scripts/backtest_liquiditysweep.py (90d fixed +$433). |
//+------------------------------------------------------------------+
void SigLiquiditySweep(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < InpLSLookback + 2 || a <= 0)
      return;
   MqlRates b = r[bars - 1];
   double rng = b.high - b.low;
   if(rng <= 0)
      return;
   double lw = MathMin(b.open, b.close) - b.low;
   double uw = b.high - MathMax(b.open, b.close);
   double lo = r[bars - 1 - InpLSLookback].low;
   double hi = r[bars - 1 - InpLSLookback].high;
   for(int i = bars - InpLSLookback; i < bars - 1; i++)
     {
      lo = MathMin(lo, r[i].low);
      hi = MathMax(hi, r[i].high);
     }

   // period-scoped arming keyed on the SIGNAL bar (mirrors ArmDual state,
   // which is safe to reuse: one strategy per EA build)
   if(b.time != g_dualPeriod)
     {
      g_dualPeriod = b.time;
      g_dualFired  = false;
      g_skipBuy    = false;
      g_skipSell   = false;
      DeleteMyPendings();
     }
   if(FindPosition() != 0)
     {
      g_dualFired = true;
      DeleteMyPendings();
      return;
     }
   if(g_dualFired)
      return;

   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_dist = MathMax((double)stops_level, (double)freeze_level) * _Point;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // bullish sweep -> buy limit at the swept low (price closed back above)
   if(b.low < lo && b.close > lo + InpLSBufAtr * a
      && lw >= InpLSWickRatio * rng)
     {
      if(!HasPendingSide(ORDER_TYPE_BUY_LIMIT) && !g_skipBuy)
        {
         if(lo <= ask - min_dist)
           {
            if(trade.BuyLimit(InpLots, lo, _Symbol, lo - 1.5 * a, lo + 3.0 * a,
                              ORDER_TIME_GTC, 0, Label()))
               Print(Label(), " LS buy-limit @ ", lo, " sl=", lo - 1.5 * a,
                     " tp=", lo + 3.0 * a);
           }
         else
           {
            Print(Label(), " LS skip buy limit (level too close/below ask)");
            g_skipBuy = true;
           }
        }
      return;
     }
   // bearish sweep -> sell limit at the swept high (price closed back below)
   if(b.high > hi && b.close < hi - InpLSBufAtr * a
      && uw >= InpLSWickRatio * rng)
     {
      if(!HasPendingSide(ORDER_TYPE_SELL_LIMIT) && !g_skipSell)
        {
         if(hi >= bid + min_dist)
           {
            if(trade.SellLimit(InpLots, hi, _Symbol, hi + 1.5 * a, hi - 3.0 * a,
                               ORDER_TIME_GTC, 0, Label()))
               Print(Label(), " LS sell-limit @ ", hi, " sl=", hi + 1.5 * a,
                     " tp=", hi - 3.0 * a);
           }
         else
           {
            Print(Label(), " LS skip sell limit (level too close/above bid)");
            g_skipSell = true;
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| SWEEPABS: M15 sweep + volume absorption, MARKET entry at the      |
//| signal close (contrast SigLiquiditySweep, which posts LIMITs at   |
//| the swept level on H4). Bullish: bar sweeps BELOW the             |
//| InpSALookback-bar low (signal bar excluded), CLOSES back above    |
//| it, lower-wick-to-close >= InpSAWickRatio of the range, and the   |
//| volume delta (close-open)*tick_volume is positive = absorbed.     |
//| Bearish mirrored. SL 1.5 ATR beyond the sweep extreme, TP 3 ATR   |
//| from the close, InpSATimeStop-bar time stop via TimeStop().       |
//| Params from scripts/backtest_institutional_v2.py (200d, cost-aware|
//| fixed -$987 / trail +$1087 PF 1.30 win 68% -- the trail arm is the|
//| strategy; the fixed twin ships as the rig's control).             |
//+------------------------------------------------------------------+
void SigSweepAbs(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < InpSALookback + 2 || a <= 0)
      return;
   MqlRates b = r[bars - 1];
   double rng = b.high - b.low;
   if(rng <= 0)
      return;
   double lo = r[bars - 1 - InpSALookback].low;
   double hi = r[bars - 1 - InpSALookback].high;
   for(int i = bars - InpSALookback; i < bars - 1; i++)
     {
      lo = MathMin(lo, r[i].low);
      hi = MathMax(hi, r[i].high);
     }
   if(FindPosition() != 0)
      return;                                    // one position, no stacking
   double vol = (double)MathMax(b.tick_volume, 1);
   double delta = (b.close - b.open) * vol;      // absorption proxy
   double px = b.close;
   if(b.low < lo && px > lo
      && (px - b.low) >= InpSAWickRatio * rng && delta > 0)
      OpenMarket(ORDER_TYPE_BUY, b.low - 1.5 * a, px + 3.0 * a);
   else if(b.high > hi && px < hi
      && (b.high - px) >= InpSAWickRatio * rng && delta < 0)
      OpenMarket(ORDER_TYPE_SELL, b.high + 1.5 * a, px - 3.0 * a);
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
   // existing SL. Ignoring either is what produced 'Modification failed due to
   // order or position being close to market' bursts under latency.
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
//| FT_FIXFADE: fade the pre-London-Fix impulse. Backtest (M15,       |
//| 90d): 46 trips +$140 PF 6.17 win 76%. The 13:00->14:00 UTC impulse |
//| >= InpFFImpulseAtr is faded at the 14:15 bar open; SL beyond the   |
//| impulse extreme + buf, TP = 1.0x impulse, InpFFTimeStop bars.      |
//| Bar times are BROKER time; convert with TimeCurrent()-TimeGMT().   |
//+------------------------------------------------------------------+
void SigFixFade(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 10 || a <= 0)
      return;
   long gmtoff = (long)(TimeCurrent() - TimeGMT());
   datetime ub = r[bars - 1].time - gmtoff;      // UTC open time of last bar
   if((long)(ub % 86400) != 14 * 3600)           // the 14:00-14:15 UTC bar
      return;
   static datetime s_lastDay = 0;                // one entry per UTC day
   datetime d = ub - (ub % 86400);
   if(d == s_lastDay)
      return;
   double impulse = r[bars - 1].close - r[bars - 5].close;  // 13:00 -> 14:15
   if(MathAbs(impulse) < InpFFImpulseAtr * a)
      return;
   double px = r[bars - 1].close;
   bool ok;
   if(impulse > 0)
      ok = OpenMarket(ORDER_TYPE_SELL, r[bars - 5].high + InpFFSLBufAtr * a,
                      px - MathAbs(impulse));
   else
      ok = OpenMarket(ORDER_TYPE_BUY, r[bars - 5].low - InpFFSLBufAtr * a,
                      px + MathAbs(impulse));
   if(ok)
     {
      s_lastDay = d;
      Print(Label(), " FIXFADE impulse=", impulse, " atr=", a);
     }
  }

//+------------------------------------------------------------------+
//| FT_VWAPREV: session-VWAP band reversion. Backtest (M15, 90d):     |
//| 86 trips +$95 PF 1.21 win 58%. VWAP anchored at the 11:00 UTC bar |
//| (London session); entry when close pierces the InpVRBandSigma band|
//| with a closing candle back toward VWAP; TP = VWAP at entry, SL    |
//| 1.5 ATR, InpVRTimeStop bars, max InpVRMaxPerDay per session.      |
//+------------------------------------------------------------------+
void SigVwapRev(const MqlRates &r[], double a)
  {
   static double s_sv = 0, s_ss = 0, s_svw = 0;
   static int    s_sigs = 0;
   static datetime s_day = 0;
   int bars = ArraySize(r);
   if(bars < 20 || a <= 0)
      return;
   MqlRates b = r[bars - 1];
   long gmtoff = (long)(TimeCurrent() - TimeGMT());
   datetime ub = b.time - gmtoff;
   long usec = (long)(ub % 86400);
   long hour = usec / 3600;
   if(hour < 11 || hour >= 20)
      return;                                    // outside session window
   datetime d = ub - usec;
   if(d != s_day)                                // new session: reset
     {
      s_day = d; s_sv = 0; s_ss = 0; s_svw = 0; s_sigs = 0;
     }
   double tprice = (b.high + b.low + b.close) / 3.0;
   double vol = (double)MathMax(b.tick_volume, 1);
   double vwap_prev = (s_svw > 0) ? s_sv / s_svw : 0;
   double var_prev = (s_svw > 0) ? s_ss / s_svw : 0;
   s_sv  += tprice * vol;
   s_svw += vol;
   s_ss  += vol * (tprice - s_sv / s_svw) * (tprice - s_sv / s_svw);
   if(s_svw <= 0 || vwap_prev <= 0)
      return;
   double sigma = MathSqrt(var_prev);
   if(sigma <= 0)
      return;
   if(FindPosition() != 0)
      return;                                    // one position, no reverse
   if(s_sigs >= InpVRMaxPerDay)
      return;
   double px = b.close;
   if(px <= vwap_prev - InpVRBandSigma * sigma && px > b.open)
     {
      if(OpenMarket(ORDER_TYPE_BUY, px - 1.5 * a, vwap_prev))
         s_sigs++;
     }
   else if(px >= vwap_prev + InpVRBandSigma * sigma && px < b.open)
     {
      if(OpenMarket(ORDER_TYPE_SELL, px + 1.5 * a, vwap_prev))
         s_sigs++;
     }
  }

//+------------------------------------------------------------------+
//| FT_DAYOPEN: weekday server-day-open long. Backtest (M15, 180d):   |
//| 190 trips +$796 PF 1.40 win 46%; weekdays only (skip the >3h      |
//| weekend gap = Monday) +$788 avg +$5.32 n=148. Entry at the FIRST  |
//| tradeable moment of the server day (first tick after the daily    |
//| break ~01:05), SL 2.0x ATR96, no TP, InpDOTimeStop-bar time stop. |
//| Matched-time long controls at 11:00/18:00 LOSE money -> the edge  |
//| is the open itself, not gold trend beta. Runs on the 5s dual path |
//| because the entry window is the day's first M15 bar (new-bar      |
//| timing would be 15 min late).                                     |
//+------------------------------------------------------------------+
void SigDayOpen(const MqlRates &r[], double a)
  {
   int bars = ArraySize(r);
   if(bars < 100)
      return;
   datetime srvNow = TimeCurrent();
   datetime dNow = srvNow - (srvNow % 86400);       // server day start
   datetime lastBar = r[bars - 1].time;             // newest closed bar
   if(dNow == lastBar - (lastBar % 86400))
      return;                                       // not the day's first bar
   static datetime s_lastDay = 0;
   if(dNow == s_lastDay)
      return;                                       // one entry per day
   long gapmin = (long)(srvNow - lastBar) / 60;     // session gap (min)
   if(gapmin > InpDOGapSkipMin)
      return;                                       // Monday (weekend gap)
   if(FindPosition() != 0)
      return;                                       // never stack
   double a96 = CalcATR(r, 96);
   if(a96 <= 0)
      return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(OpenMarket(ORDER_TYPE_BUY, ask - InpDOSLAtr * a96, 0))
     {
      s_lastDay = dNow;
      Print(Label(), " DAYOPEN entry gap=", gapmin, "min atr96=", a96);
     }
  }

//+------------------------------------------------------------------+
//| Time stop for the fixfade/vwaprev/dayopen twins (backtest parity) |
//+------------------------------------------------------------------+
void TimeStop()
  {
   int maxb = (EA_STRATEGY == FT_DAYOPEN) ? InpDOTimeStop :
              (EA_STRATEGY == FT_FIXFADE) ? InpFFTimeStop :
              (EA_STRATEGY == FT_VWAPREV) ? InpVRTimeStop :
              (EA_STRATEGY == FT_SWEEPABS) ? InpSATimeStop : 0;
   if(maxb <= 0)
      return;
   ulong t = FindPosition();
   if(t == 0)
      return;
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
   if(TimeCurrent() - opened >= maxb * PeriodSeconds(InpTimeframe))
     {
      if(trade.PositionClose(t))
         Print(Label(), " TIME-STOP close after ", maxb, " bars");
     }
  }

//+------------------------------------------------------------------+
void DispatchSignal(const MqlRates &r[], double a)
  {
   switch(EA_STRATEGY)
     {
      case FT_BREAKOUT: SigBreakout(r, a); break;
      case FT_MEANREV:  SigMeanrev(r, a);  break;
      case FT_MACROSS:  SigMacross(r, a);  break;
      case FT_STRADDLE: SigStraddle(r, a); break;
      case FT_SMC:      SigSMC(r, a);      break;
      case FT_LONDON:   SigLondon(r, a);   break;
      case FT_SQUEEZE:  SigSqueeze(r, a);  break;
      case FT_PROFILE:  SigProfile(r, a);  break;
      case FT_ORDERFLOW: SigOrderflow(r, a); break;
      case FT_TRENDPULLBACK: SigTrendPullback(r, a); break;
      case FT_DONCHIAN:  SigDonchian(r, a);  break;
      case FT_TREND:     SigTrend(r, a);     break;
      case FT_SUPRES:    SigSupRes(r, a);    break;
      case FT_SUPERTREND: SigSupertrend(r, a); break;
      case FT_LIQUIDITYSWEEP: SigLiquiditySweep(r, a); break;
      case FT_FIXFADE:  SigFixFade(r, a);  break;
      case FT_VWAPREV:  SigVwapRev(r, a);  break;
      case FT_DAYOPEN:  SigDayOpen(r, a);  break;
      case FT_SWING:    SigSwing(r, a);    break;
      case FT_SWEEPABS: SigSweepAbs(r, a); break;
     }
  }

//+------------------------------------------------------------------+
//| Stuck-stop guard: the broker server can lag badly (2026-09-29:    |
//| p90 order ack 60s+), leaving price THROUGH an SL/TP with nothing  |
//| executing. FIX 2026-09-30: the old pulse-then-close design was    |
//| dead weight -- once price crosses a stop, that stop sits on the   |
//| WRONG side of price, so no SL/TP modify can ever be valid (the    |
//| journal showed 190 'Invalid stops' failed modifies in 3 days, one |
//| every 20s, while losses ran to 6.6 ATR). Now: breach > threshold  |
//| persisting InpStuckPersistSec arms the guard; if the breach is    |
//| still there after InpStuckGiveupSec, market-close the position.   |
//| The python watchdog (stuck_stop_watchdog.py) alerts instantly and |
//| stays as the runner-side backstop.                                |
//| Each instance holds at most one position, so state is single-slot.| 
//+------------------------------------------------------------------+
input group             "Stuck-stop guard"
input bool   InpStuckGuard      = true;  // Close position stuck past SL/TP
input int    InpStuckThreshPts  = 50;    // Min breach beyond stop (points)
input int    InpStuckPersistSec = 30;    // Legacy (unused since the 09-30 fix)
input int    InpStuckGiveupSec  = 180;   // Breach persists this long -> close (s)

void StuckStopGuard()
  {
   if(!InpStuckGuard)
      return;
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(pt <= 0)
      return;
   double thresh = InpStuckThreshPts * pt;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   // find OUR position crossing a stop (one position per instance)
   ulong  ticket = 0;
   double stop = 0, psl = 0, ptp = 0;
   bool   isBuy = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      bool   b  = false;
      double s  = 0;
      if(ptype == POSITION_TYPE_BUY)
        {
         if(sl > 0 && tick.bid < sl - thresh) { s = sl; b = true; }
         else if(tp > 0 && tick.bid > tp + thresh) { s = tp; b = true; }
        }
      else
        {
         if(sl > 0 && tick.ask > sl + thresh) { s = sl; b = true; }
         else if(tp > 0 && tick.ask < tp - thresh) { s = tp; b = true; }
        }
      if(b)
        {
         ticket = t; stop = s; psl = sl; ptp = tp;
         isBuy = (ptype == POSITION_TYPE_BUY);
         break; // position stays selected for the ops below
        }
     }

   static ulong    s_ticket  = 0;
   static datetime s_since   = 0;
   static int      s_resent  = 0;
   static datetime s_lastTry = 0;
   if(ticket == 0)
     {
      s_ticket = 0; s_since = 0; s_resent = 0; s_lastTry = 0;
      return;                    // no breach: (re)arm silently
     }
   if(ticket != s_ticket)
     {
      s_ticket = ticket; s_since = TimeCurrent();
      s_resent = 0; s_lastTry = 0;
     }
   long held = (long)(TimeCurrent() - s_since);
   if(held < InpStuckGiveupSec)
      return;                 // breach not yet old enough -> let the server catch up
   if(s_lastTry > 0 && TimeCurrent() - s_lastTry < 20)
      return;                 // retry a failed close at most every 20s
   s_lastTry = TimeCurrent();

   // breached stop = wrong side of price: modifying is impossible, closing
   // is the only valid action. Log-and-close (retry every 20s on failure).
   if(trade.PositionClose(ticket))
     {
      Print(Label(), " STUCK-STOP CLOSE #", ticket, " after ", held,
            "s breached (stop=", stop, " sl=", psl, " tp=", ptp,
            ") ret=", trade.ResultRetcode());
      s_ticket = 0; s_since = 0; s_resent = 0; s_lastTry = 0;
     }
   else
      Print(Label(), " STUCK-STOP CLOSE #", ticket, " FAILED ret=",
            trade.ResultRetcode(), " (", trade.ResultRetcodeDescription(),
            ") will retry");
  }

void OnTick()
  {
   TrailStop(); // runs every tick so trailing reacts to live price
   StuckStopGuard(); // re-trigger SL/TP the broker left unexecuted
   TimeStop();  // fixfade/vwaprev backtest parity time stops

   // dual-stop strategies arm/retry every few seconds (not just on new bars)
   // so a failed send is retried within the period; the liquidity-sweep
   // limit re-arming uses the same state machine; dayopen needs the 5s
   // cadence because its entry window is the day's first bar
   if(EA_STRATEGY == FT_STRADDLE || EA_STRATEGY == FT_LONDON
      || EA_STRATEGY == FT_LIQUIDITYSWEEP || EA_STRATEGY == FT_DAYOPEN)
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
      DispatchSignal(dr, da);
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

   // FT_TRENDPULLBACK reads the REAL H1 feed for its trend leg (previous
   // closed H1 close vs EMA50); the M15 bars stay in r[] for entry logic.
   // FT_SWING does the same: its bias leg is H1 structure.
   if(EA_STRATEGY == FT_TRENDPULLBACK || EA_STRATEGY == FT_SWING)
     {
      g_h1n = CopyRates(_Symbol, PERIOD_H1, 1, 400, g_h1);
      if(g_h1n < 60)
         return;
     }
   DispatchSignal(r, g_atr);
  }
//+------------------------------------------------------------------+
#endif // __FTTEST_CORE_MQH__
