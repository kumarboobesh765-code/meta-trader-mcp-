//+------------------------------------------------------------------+
//| AetherFlowEA.mq5                                                  |
//| AETHER FLOW SYSTEM - Mxwll Fusion Engine (LuxAlgo OB Edition)     |
//| MQL5 EA port of the Pine Script v6 indicator by Fatich.id         |
//|                                                                   |
//| Every signal engine of the indicator is ported to MQL5:           |
//|   - UT Bot (adaptive ATR trailing stop, Key Value + ATR Period)   |
//|   - Hull Suite (HMA/THMA/EHMA band, trend color flips)            |
//|   - SMC Market Structure (internals/externals, CHoCH/BOS, HH/LH)  |
//|   - FVG (Fair Value Gaps with mitigation tracking)                |
//|   - LuxAlgo Order Blocks (volume pivot detection + mitigation)    |
//|   - Three-Bar Reversal (trend filtered, detection + confirmation) |
//|   - Reversal Signals (TD-style momentum count + S/R levels)       |
//|                                                                   |
//| Trading engine (mirrors FTTestEA.mq5 conventions):                |
//|   - All engines replay over CLOSED bars on every new bar; state   |
//|     is rebuilt deterministically (restart-safe, no repaint)       |
//|   - TRADE_UT_ONLY   : trade UT Bot flips only                     |
//|   - TRADE_CONFLUENCE: trade when >= InpMinConfluence modules      |
//|     point the same way and at least one "hard" event fired        |
//|   - TRADE_SIGNAL_ONLY: chart comment only, no orders              |
//|   - SL/TP always set (ATR based), optional trailing twin          |
//|   - Demo-only guard (InpAllowReal) like all FTTest EAs            |
//|                                                                   |
//| Magic: 9500xx fixed / 9600xx trailing                             |
//+------------------------------------------------------------------+
#property copyright "AETHER FLOW SYSTEM - MQL5 port of the Pine Script v6 indicator by Fatich.id"
#property link      "https://t.me/fatichid"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Enums                                                             |
//+------------------------------------------------------------------+
enum ENUM_UT_HULL_SRC
  {
   UT_SRC_CLOSE = 0,  // Close
   UT_SRC_HA    = 1   // Heikin Ashi close
  };

enum ENUM_HULL_MODE
  {
   HULL_HMA  = 0,  // Hma
   HULL_THMA = 1,  // Thma
   HULL_EHMA = 2   // Ehma
  };

enum ENUM_3BR_TREND
  {
   T3BR_NONE       = 0,  // None
   T3BR_MACLOUD    = 1,  // Moving Average Cloud
   T3BR_SUPERTREND = 2,  // Supertrend
   T3BR_DONCHIAN   = 3   // Donchian Channels
  };

enum ENUM_MA3_TYPE
  {
   MA3_SMA  = 0,  // SMA
   MA3_EMA  = 1,  // EMA
   MA3_HMA  = 2,  // HMA
   MA3_RMA  = 3,  // RMA
   MA3_WMA  = 4,  // WMA
   MA3_VWMA = 5   // VWMA
  };

enum ENUM_TRADING_MODE
  {
   TRADE_UT_ONLY     = 0,  // UT Bot signals only
   TRADE_CONFLUENCE  = 1,  // Confluence: N modules must align
   TRADE_SIGNAL_ONLY = 2   // No trading - chart signals only
  };

//+------------------------------------------------------------------+
//| Inputs                                                            |
//+------------------------------------------------------------------+
input group             "Core"
input ENUM_TIMEFRAMES   InpTimeframe     = PERIOD_M15;    // Signal timeframe
input double            InpLots          = 0.01;          // Lot size (fixed)
input int               InpMagic         = 0;             // Magic (9500xx fixed / 9600xx trailing; 0 = refuse)
input ENUM_TRADING_MODE InpTradingMode   = TRADE_UT_ONLY; // Trading mode
input int               InpMinConfluence = 3;             // Min modules aligned (confluence mode)

input group             "Trailing SL (true for the -T twin)"
input bool              InpUseTrailing  = false;          // Use trailing SL
input double            InpTrailActAtr  = 1.0;            // Activate after (x ATR)
input double            InpTrailDistAtr = 1.2;            // Trail distance (x ATR)
input double            InpTrailStepAtr = 0.3;            // Min SL move (x ATR)

input group             "Safety"
input bool              InpAllowReal    = false;          // Allow REAL accounts
input int               InpDeviationPts = 50;             // Max slippage (points)

input group             "UT Bot Settings"
input double            InpUTKeyValue   = 2.0;            // UT Key Value (a)
input int               InpUTAtrPeriod  = 6;              // UT ATR Period (c)
input bool              InpUTHeikinAshi = false;          // UT Signals from Heikin Ashi

input group             "Hull Suite Settings"
input int               InpHullLength    = 55;            // Hull Length
input double            InpHullMult      = 1.0;           // Hull Length multiplier
input ENUM_HULL_MODE    InpHullMode      = HULL_HMA;      // Hull Variation
input ENUM_UT_HULL_SRC  InpHullSrc       = UT_SRC_CLOSE;  // Hull Source
input bool              InpUseHullFilter = false;         // Block trades against Hull trend

input group             "Smart Money Concepts"
input int               InpIntSens        = 5;            // Internals sensitivity (swing length)
input int               InpExtSens        = 25;           // Externals sensitivity (swing length)
input bool              InpTradeCHoCHOnly = false;        // Only trade CHoCH (skip BoS)

input group             "FVG"
input bool              InpShowFVG        = true;         // Track FVGs (confluence module)
input double            InpFVGThreshold   = 0.0;          // FVG threshold % (0 = all)
input bool              InpTradeFVGRetest = false;        // Confluence: FVG retest counts as event

input group             "LuxAlgo Order Blocks"
input bool              InpShowOB        = true;          // Track Order Blocks (confluence module)
input int               InpOBPivotLen    = 5;             // Volume Pivot Length
input bool              InpTradeOBRetest = false;         // Confluence: OB retest counts as event

input group             "Three Bar Reversal"
input bool              InpShow3BR       = true;          // Track Three Bar Reversal (confluence module)
input ENUM_3BR_TREND    Inp3BRTrendType  = T3BR_NONE;     // Trend filter
input ENUM_MA3_TYPE     Inp3BRMaType     = MA3_HMA;       // MA Type (cloud)
input int               Inp3BRMaFast     = 50;            // Fast MA Length
input int               Inp3BRMaSlow     = 200;           // Slow MA Length
input int               Inp3BRStAtr      = 10;            // ST ATR Length
input double            Inp3BRStFactor   = 3.0;           // ST Factor
input int               Inp3BRDcLength   = 13;            // DC Length
input bool              Inp3BRAligned    = true;          // Aligned (true) or Opposite (false)

input group             "Reversal Signals"
input bool              InpShowRS       = true;           // Track momentum count (confluence module)

input group             "Risk"
input int               InpSlAtrMult    = 2;              // SL distance (x ATR)
input int               InpTpAtrMult    = 3;              // TP distance (x ATR)
input int               InpATimeStop    = 0;              // Max hold (bars, 0 = off)

//+------------------------------------------------------------------+
//| State structures                                                  |
//+------------------------------------------------------------------+
struct SFvg
  {
   double   max;
   double   min;
   bool     isbull;
   datetime t;
  };

struct SOb
  {
   double   top;
   double   btm;
   double   avg;
   datetime left;
  };

// SMC structure chain (used for both externals and internals)
struct SStruct
  {
   double upAxis;      // last confirmed swing high
   double dnAxis;      // last confirmed swing low
   int    intra;       // 0 = breaking up / 1 = breaking down (Pine intraCalc)
   int    upside;      // liquidity flag above swing high (1 armed / 0 consumed)
   int    downside;    // liquidity flag below swing low
   int    moving;      // 1 bull leg / -1 bear leg / 0 unset
   int    evBull;      // this bar: bullish structure break
   int    evBear;      // this bar: bearish structure break
   int    kindBull;    // 1 = CHoCH / 2 = BoS
   int    kindBear;    // 1 = CHoCH / 2 = BoS
  };

//+------------------------------------------------------------------+
//| Globals                                                           |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_name    = "aetherflow";
double   g_atr     = 0;             // SMA ATR(14) for SL/TP/trailing (project convention)
datetime g_lastTrailFail = 0;       // trailing-modify failure backoff (see TrailStop)
datetime g_lastBar = 0;

// closed-bar window: g_r[0] = oldest ... g_r[g_n-1] = latest CLOSED bar
MqlRates g_r[];
int      g_n = 0;

// --- bar access (FORWARD index: i=0 oldest ... g_n-1 = latest CLOSED bar) ---
double Hi(int i) { return(g_r[i].high);                }
double Lo(int i) { return(g_r[i].low);                 }
double Op(int i) { return(g_r[i].open);                }
double Cl(int i) { return(g_r[i].close);               }
double Vl(int i) { return((double)g_r[i].tick_volume); }

// --- UT Bot ---
bool    g_utFirst   = true;
double  g_utStop    = 0.0;   // xATRTrailingStop
double  g_utSrcPrev = 0.0;   // srcUT[1]
int     g_utPos     = 0;     // 1 / -1 / 0
bool    g_utBuy     = false; // events of the latest closed bar
bool    g_utSell    = false;
double  g_utAtr     = 0.0;   // Wilder ATR (UT ATR Period)

// --- Hull Suite ---
double  g_hull      = 0;     // hull at latest closed bar
double  g_hullPrev2 = 0;     // hull[2]
bool    g_hullUp    = false; // hull > hull[2] (green)

// --- SMC structure ---
SStruct g_ext, g_int;

// --- FVG ---
SFvg   g_fvgs[];                        // [size-1] = newest
int    g_fvgBullCount = 0, g_fvgBearCount = 0;
int    g_fvgBullMit   = 0, g_fvgBearMit   = 0;
bool   g_fvgBullRetest = false, g_fvgBearRetest = false;  // latest-bar retest flags

// --- Order Blocks ---
SOb    g_bullObs[], g_bearObs[];
int    g_obBullCount = 0, g_obBearCount = 0;
int    g_obBullMit   = 0, g_obBearMit   = 0;
bool   g_obBullNew   = false, g_obBearNew   = false;     // OB formed this bar
bool   g_obBullRetest = false, g_obBearRetest = false;
int    g_os = 0;                                            // Pine os (breaker structure)

// --- Three Bar Reversal ---
int     g_3brOs = 0;                    // Donchian os (3BR)
bool    g_bull3brProcess = false, g_bear3brProcess = false;
bool    g_bull3brEvent   = false, g_bear3brEvent   = false;   // detection this bar
bool    g_bull3brConfirm = false, g_bear3brConfirm = false;   // confirmation this bar
double  g_bull3brLnAT = 0, g_bull3brLnAB = 0;   // bull: top = high[2], bottom = min(low[1], low)
double  g_bear3brLnST = 0, g_bear3brLnSB = 0;   // bear: top = max(high[1], high), bottom = low[2]
double  g_bull3brHigh = 0, g_bear3brLow = 0;    // S/R level (brpSR = "Level")

// --- Reversal Signals (momentum count) ---
int     g_bSCRS = 0, g_sSCRS = 0;
bool    g_showBullMom = false, g_showBearMom = false;
double  g_bSRRS = 0, g_sSSRS = 0;       // S/R levels (price > level invalidates)
bool    g_bSRRSOn = false, g_sSSRSOn = false;

// --- scratch series (rebuilt each replay) ---
double  g_srcHull[];                    // hull source series
double  g_hullArr[];                    // hull values per bar
double  g_maF[], g_maS[];               // 3BR MA cloud
double  g_closes[];                     // close series for MA cloud
int     g_stDir[];                      // supertrend direction per bar (-1 up / +1 dn)

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
      Print("REFUSING: InpMagic must be set explicitly (9500xx fixed / 9600xx trailing).");
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
         " lots=", InpLots, " mode=", EnumToString(InpTradingMode),
         " trailing=", InpUseTrailing ? "ON" : "OFF",
         " timestop=", InpATimeStop, "bars");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   Comment("");
  }

//+------------------------------------------------------------------+
//| SMA ATR over the window (SL/TP sizing, project convention)        |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| Series math helpers (out[i] defined for every i; warmup clamped)  |
//+------------------------------------------------------------------+
void CalcWMA(const double &src[], int period, double &out[])
  {
   int n = ArraySize(src);
   if(period < 1)
      period = 1;
   ArrayResize(out, n);
   double denom = period * (period + 1) / 2.0;
   for(int i = 0; i < n; i++)
     {
      if(i < period - 1)
        {
         out[i] = src[i];
         continue;
        }
      double s = 0.0;
      for(int k = 0; k < period; k++)
         s += src[i - k] * (period - k);
      out[i] = s / denom;
     }
  }

void CalcEMA(const double &src[], int period, double &out[])
  {
   int n = ArraySize(src);
   ArrayResize(out, n);
   double k = 2.0 / (period + 1);
   out[0] = src[0];
   for(int i = 1; i < n; i++)
      out[i] = src[i] * k + out[i - 1] * (1 - k);
  }

void CalcRMA(const double &src[], int period, double &out[])
  {
   int n = ArraySize(src);
   ArrayResize(out, n);
   int p = MathMin(period, n);
   double seed = 0.0;
   for(int i = 0; i < p; i++)
      seed += src[i];
   seed /= p;
   for(int i = 0; i < n; i++)
     {
      if(i < period)
         out[i] = seed;
      else
         out[i] = (out[i - 1] * (period - 1) + src[i]) / period;
     }
  }

void CalcSMA(const double &src[], int period, double &out[])
  {
   int n = ArraySize(src);
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      int p = MathMin(period, i + 1);
      double s = 0.0;
      for(int k = 0; k < p; k++)
         s += src[i - k];
      out[i] = s / p;
     }
  }

void CalcVWMA(const double &src[], int period, double &out[])
  {
   int n = ArraySize(src);
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      int p = MathMin(period, i + 1);
      double sp = 0.0, sv = 0.0;
      for(int k = 0; k < p; k++)
        {
         double v = Vl(i - k);
         sp += src[i - k] * v;
         sv += v;
        }
      out[i] = (sv > 0) ? sp / sv : src[i];
     }
  }

// Plain HMA over a series (for the 3BR MA cloud)
void CalcHMA(const double &src[], int len, double &out[])
  {
   int n = ArraySize(src);
   double a[], b[], d[];
   ArrayResize(d, n);
   CalcWMA(src, MathMax(1, len / 2), a);
   CalcWMA(src, MathMax(2, len), b);
   for(int i = 0; i < n; i++)
      d[i] = 2 * a[i] - b[i];
   CalcWMA(d, (int)MathMax(1, (int)MathRound(MathSqrt((double)MathMax(2, len)))), out);
  }

//+------------------------------------------------------------------+
//| Hull Suite array (Pine Mode(): Hma/Thma/Ehma)                     |
//+------------------------------------------------------------------+
void CalcHullArray(const double &src[], double &out[])
  {
   int n   = ArraySize(src);
   int len = (int)MathMax(2.0, MathRound(InpHullLength * InpHullMult));
   double a[], b[], c[], d[];
   ArrayResize(d, n);
   if(InpHullMode == HULL_EHMA)
     {
      CalcEMA(src, MathMax(1, len / 2), a);
      CalcEMA(src, MathMax(2, len), b);
      for(int i = 0; i < n; i++)
         d[i] = 2 * a[i] - b[i];
      CalcEMA(d, (int)MathMax(1, (int)MathRound(MathSqrt((double)len))), out);
     }
   else if(InpHullMode == HULL_THMA)
     {
      // Pine Mode(): THMA(src, len/2) = wma(3*wma(src,m/3)-wma(src,m/2)-wma(src,m), m)
      int m = (int)MathMax(2, len / 2);
      CalcWMA(src, MathMax(1, m / 3), a);
      CalcWMA(src, MathMax(1, m / 2), b);
      CalcWMA(src, m, c);
      for(int i = 0; i < n; i++)
         d[i] = 3 * a[i] - b[i] - c[i];
      CalcWMA(d, m, out);
     }
   else // HMA
     {
      CalcWMA(src, MathMax(1, len / 2), a);
      CalcWMA(src, MathMax(2, len), b);
      for(int i = 0; i < n; i++)
         d[i] = 2 * a[i] - b[i];
      CalcWMA(d, (int)MathMax(1, (int)MathRound(MathSqrt((double)len))), out);
     }
  }

//+------------------------------------------------------------------+
//| 3BR MA cloud dispatcher                                           |
//+------------------------------------------------------------------+
void CalcMAArray(const double &src[], int period, ENUM_MA3_TYPE type, double &out[])
  {
   switch(type)
     {
      case MA3_EMA:  CalcEMA(src, period, out);    break;
      case MA3_RMA:  CalcRMA(src, period, out);    break;
      case MA3_HMA:  CalcHMA(src, period, out);    break;
      case MA3_WMA:  CalcWMA(src, period, out);    break;
      case MA3_VWMA: CalcVWMA(src, period, out);   break;
      default:       CalcSMA(src, period, out);    break;
     }
  }

//+------------------------------------------------------------------+
//| Supertrend direction per bar (Pine ta.supertrend port)            |
//| dir: -1 = uptrend (band below price), +1 = downtrend              |
//+------------------------------------------------------------------+
void CalcSupertrend(int atrPeriod, double factor, int &dir[])
  {
   int n = g_n;
   ArrayResize(dir, n);
   double tr[], atr[], ub[], lb[], st[];
   ArrayResize(tr, n);  ArrayResize(atr, n);
   ArrayResize(ub, n);  ArrayResize(lb, n);  ArrayResize(st, n);
   for(int i = 0; i < n; i++)
     {
      if(i == 0)
         tr[i] = Hi(i) - Lo(i);
      else
         tr[i] = MathMax(Hi(i) - Lo(i),
                MathMax(MathAbs(Hi(i) - Cl(i - 1)), MathAbs(Lo(i) - Cl(i - 1))));
     }
   CalcRMA(tr, atrPeriod, atr);
   for(int i = 0; i < n; i++)
     {
      double src = (Hi(i) + Lo(i)) / 2.0;
      double up  = src + factor * atr[i];
      double dn  = src - factor * atr[i];
      if(i == 0)
        {
         ub[i] = up; lb[i] = dn; st[i] = dn; dir[i] = 1;
         continue;
        }
      double prevUb = ub[i - 1], prevLb = lb[i - 1];
      lb[i] = (dn > prevLb || Cl(i - 1) < prevLb) ? dn : prevLb;
      ub[i] = (up < prevUb || Cl(i - 1) > prevUb) ? up : prevUb;
      if(st[i - 1] == prevUb)
         dir[i] = (Cl(i) > up) ? -1 : 1;
      else
         dir[i] = (Cl(i) < dn) ? 1 : -1;
      st[i] = (dir[i] == -1) ? lb[i] : ub[i];
     }
  }

//+------------------------------------------------------------------+
//| Replay reset                                                      |
//+------------------------------------------------------------------+
void ReplayReset()
  {
   g_utFirst = true; g_utStop = 0; g_utSrcPrev = 0; g_utPos = 0;
   g_utBuy = false; g_utSell = false; g_utAtr = 0;

   ZeroSStruct(g_ext);
   ZeroSStruct(g_int);

   ArrayResize(g_fvgs, 0);
   g_fvgBullCount = 0; g_fvgBearCount = 0;
   g_fvgBullMit = 0;   g_fvgBearMit = 0;
   g_fvgBullRetest = false; g_fvgBearRetest = false;

   ArrayResize(g_bullObs, 0);
   ArrayResize(g_bearObs, 0);
   g_obBullCount = 0; g_obBearCount = 0;
   g_obBullMit = 0;   g_obBearMit = 0;
   g_obBullNew = false; g_obBearNew = false;
   g_obBullRetest = false; g_obBearRetest = false;
   g_os = 0;

   g_3brOs = 0;
   g_bull3brProcess = false; g_bear3brProcess = false;
   g_bull3brEvent = false;   g_bear3brEvent = false;
   g_bull3brConfirm = false; g_bear3brConfirm = false;
   g_bull3brLnAT = 0; g_bull3brLnAB = 0;
   g_bear3brLnST = 0; g_bear3brLnSB = 0;
   g_bull3brHigh = 0; g_bear3brLow = 0;

   g_bSCRS = 0; g_sSCRS = 0;
   g_showBullMom = false; g_showBearMom = false;
   g_bSRRS = 0; g_sSSRS = 0;
   g_bSRRSOn = false; g_sSSRSOn = false;
  }

void ZeroSStruct(SStruct &s)
  {
   s.upAxis = 0; s.dnAxis = 0; s.intra = 0;
   s.upside = 1; s.downside = 1; s.moving = 0;
   s.evBull = 0; s.evBear = 0; s.kindBull = 0; s.kindBear = 0;
  }

//+------------------------------------------------------------------+
//| UT Bot step (exact Pine state machine)                            |
//| Note: the Pine "Heikin Ashi" source reads HA values of the same   |
//| chart; here we synthesize the HA close from regular bars.         |
//+------------------------------------------------------------------+
void StepUT(int i)
  {
   double src = InpUTHeikinAshi
                ? (Op(i) + Hi(i) + Lo(i) + Cl(i)) / 4.0
                : Cl(i);

   // Wilder ATR (ta.atr = RMA of TR)
   double tr = (i == 0)
               ? Hi(i) - Lo(i)
               : MathMax(Hi(i) - Lo(i),
                 MathMax(MathAbs(Hi(i) - Cl(i - 1)), MathAbs(Lo(i) - Cl(i - 1))));
   if(i == 0)
      g_utAtr = tr;
   else
      g_utAtr = (g_utAtr * (InpUTAtrPeriod - 1) + tr) / InpUTAtrPeriod;

   double nLoss    = InpUTKeyValue * g_utAtr;
   double prevStop = g_utStop;
   double prevSrc  = g_utSrcPrev;

   if(g_utFirst)
     {
      g_utStop  = src - nLoss;   // Pine first-bar branch (nz -> 0)
      g_utFirst = false;
     }
   else
     {
      if(src > prevStop && prevSrc > prevStop)
         g_utStop = MathMax(prevStop, src - nLoss);
      else if(src < prevStop && prevSrc < prevStop)
         g_utStop = MathMin(prevStop, src + nLoss);
      else if(src > prevStop)
         g_utStop = src - nLoss;
      else
         g_utStop = src + nLoss;

      // Pine pos: compares srcUT[1] vs stop[1] and srcUT vs stop[1]
      if(prevSrc < prevStop && src > prevStop)
         g_utPos = 1;
      else if(prevSrc > prevStop && src < prevStop)
         g_utPos = -1;
      // else keep previous pos
     }

   // ta.ema(srcUT,1) == srcUT, so crossovers reduce to src vs trailing stop
   bool above = (src > g_utStop) && (prevSrc <= prevStop);
   bool below = (g_utStop > src) && (prevStop <= prevSrc);

   g_utBuy  = (src > g_utStop) && above;
   g_utSell = (src < g_utStop) && below;

   g_utSrcPrev = src;
  }

//+------------------------------------------------------------------+
//| SMC structure step (Mxwll calculatePivots + drawStructure port)   |
//+------------------------------------------------------------------+
void StepStructure(SStruct &st, int S, int i)
  {
   st.evBull = 0; st.evBear = 0; st.kindBull = 0; st.kindBear = 0;
   if(i < S)   // need S+1 bars of history
      return;

   int prevIntra = st.intra;

   // Pine: up = slice(0,length).max() of the S bars up to 'now';
   // cHi/cLo = the bar S bars back (the candidate swing).
   double cHi = Hi(i - S), cLo = Lo(i - S);
   double maxRecent = Hi(i), minRecent = Lo(i);
   for(int k = 1; k < S; k++)
     {
      maxRecent = MathMax(maxRecent, Hi(i - k));
      minRecent = MathMin(minRecent, Lo(i - k));
     }

   int intra = prevIntra;
   if(cHi > maxRecent)
      intra = 0;
   else if(cLo < minRecent)
      intra = 1;
   st.intra = intra;

   double topSwing = (intra == 0 && prevIntra != 0) ? cHi : 0;
   double botSwing = (intra == 1 && prevIntra != 1) ? cLo : 0;

   if(topSwing != 0)
     {
      st.upside = 1;
      st.upAxis = topSwing;
     }
   if(botSwing != 0)
     {
      st.downside = 1;
      st.dnAxis   = botSwing;
     }

   // Pine ta.crossover(close, axis): axis is a single value for this bar,
   // so both legs of the comparison use the (possibly just-updated) axis.
   if(st.upAxis > 0 && Cl(i) > st.upAxis && Cl(i - 1) <= st.upAxis)
     {
      if(st.upside != 0)
        {
         st.evBull   = 1;
         st.kindBull = (st.moving < 0) ? 1 : 2;   // CHoCH / BoS
         st.upside   = 0;
         st.moving   = 1;
        }
     }
   if(st.dnAxis > 0 && Cl(i) < st.dnAxis && Cl(i - 1) >= st.dnAxis)
     {
      if(st.downside != 0)
        {
         st.evBear   = 1;
         st.kindBear = (st.moving > 0) ? 1 : 2;
         st.downside = 0;
         st.moving   = -1;
        }
     }
  }

//+------------------------------------------------------------------+
//| FVG step (LuxAlgo detectFVG + mitigation)                         |
//+------------------------------------------------------------------+
void StepFVG(int i)
  {
   if(i < 2)
      return;
   double threshold = InpFVGThreshold / 100.0;

   bool bull_fvg = Lo(i) > Hi(i - 2) &&
                   Cl(i - 1) > Hi(i - 2) &&
                   (Lo(i) - Hi(i - 2)) / Hi(i - 2) > threshold;
   bool bear_fvg = Hi(i) < Lo(i - 2) &&
                   Cl(i - 1) < Lo(i - 2) &&
                   (Lo(i - 2) - Hi(i)) / Hi(i) > threshold;

   if(bull_fvg)
     {
      SFvg f;
      f.max = Lo(i); f.min = Hi(i - 2); f.isbull = true; f.t = g_r[i].time;
      int sz = ArraySize(g_fvgs);
      ArrayResize(g_fvgs, sz + 1);
      g_fvgs[sz] = f;
      g_fvgBullCount++;
     }
   else if(bear_fvg)
     {
      SFvg f;
      f.max = Lo(i - 2); f.min = Hi(i); f.isbull = false; f.t = g_r[i].time;
      int sz = ArraySize(g_fvgs);
      ArrayResize(g_fvgs, sz + 1);
      g_fvgs[sz] = f;
      g_fvgBearCount++;
     }

   // mitigation: iterate newest -> oldest, remove filled zones
   for(int k = ArraySize(g_fvgs) - 1; k >= 0; k--)
     {
      if(g_fvgs[k].isbull && Cl(i) < g_fvgs[k].min)
        {
         FvgRemove(k);
         g_fvgBullMit++;
        }
      else if(!g_fvgs[k].isbull && Cl(i) > g_fvgs[k].max)
        {
         FvgRemove(k);
         g_fvgBearMit++;
        }
     }
  }

void FvgRemove(int k)
  {
   int n = ArraySize(g_fvgs);
   for(int m = k; m < n - 1; m++)
      g_fvgs[m] = g_fvgs[m + 1];
   ArrayResize(g_fvgs, n - 1);
  }

//+------------------------------------------------------------------+
//| LuxAlgo Order Blocks step (volume pivot + Wick mitigation)        |
//+------------------------------------------------------------------+
void StepOB(int i)
  {
   g_obBullNew = false;
   g_obBearNew = false;

   int len = InpOBPivotLen;
   if(i < 2 * len)
      return;

   // ta.highest/ta.lowest(lengthOB): window of 'len' bars ending at bar i
   double upper = Hi(i), lower = Lo(i);
   for(int k = 1; k < len; k++)
     {
      upper = MathMax(upper, Hi(i - k));
      lower = MathMin(lower, Lo(i - k));
     }

   // os (breaker structure): extreme 'len' bars back vs the current window
   if(Hi(i - len) > upper)
      g_os = 0;
   else if(Lo(i - len) < lower)
      g_os = 1;

   // volume pivot high at bar i-len (strict on both sides, like ta.pivothigh)
   bool phv = true;
   double pv = Vl(i - len);
   for(int k = 1; k <= len && phv; k++)
      if(!(pv > Vl(i - len - k)))
         phv = false;
   for(int k = 1; k <= len && phv; k++)
      if(!(pv > Vl(i - len + k)))
         phv = false;

   if(phv && g_os == 1)
     {
      SOb b;
      b.top  = (Hi(i - len) + Lo(i - len)) / 2.0;   // hl2[len]
      b.btm  = Lo(i - len);                         // low[len]
      b.avg  = (b.top + b.btm) / 2.0;
      b.left = g_r[i - len].time;
      int sz = ArraySize(g_bullObs);
      ArrayResize(g_bullObs, sz + 1);
      g_bullObs[sz] = b;
      g_obBullCount++;
      g_obBullNew = true;
     }
   if(phv && g_os == 0)
     {
      SOb b;
      b.top  = Hi(i - len);                         // high[len]
      b.btm  = (Hi(i - len) + Lo(i - len)) / 2.0;   // hl2[len]
      b.avg  = (b.top + b.btm) / 2.0;
      b.left = g_r[i - len].time;
      int sz = ArraySize(g_bearObs);
      ArrayResize(g_bearObs, sz + 1);
      g_bearObs[sz] = b;
      g_obBearCount++;
      g_obBearNew = true;
     }

   // mitigation ('Wick' method: window extreme vs OB boundary)
   for(int k = ArraySize(g_bullObs) - 1; k >= 0; k--)
      if(lower < g_bullObs[k].btm)
        {
         ObRemove(g_bullObs, k);
         g_obBullMit++;
        }
   for(int k = ArraySize(g_bearObs) - 1; k >= 0; k--)
      if(upper > g_bearObs[k].top)
        {
         ObRemove(g_bearObs, k);
         g_obBearMit++;
        }
  }

void ObRemove(SOb &arr[], int k)
  {
   int n = ArraySize(arr);
   for(int m = k; m < n - 1; m++)
      arr[m] = arr[m + 1];
   ArrayResize(arr, n - 1);
  }

//+------------------------------------------------------------------+
//| Three Bar Reversal step (Pine state machine port)                 |
//+------------------------------------------------------------------+
void Step3BR(int i, bool bullTrend, bool bearTrend)
  {
   if(i < 2)
      return;

   g_bull3brEvent = false;   g_bear3brEvent = false;
   g_bull3brConfirm = false; g_bear3brConfirm = false;

   bool bullPat = (Cl(i - 2) < Op(i - 2)) &&
                  (Lo(i - 1) < Lo(i - 2)) && (Hi(i - 1) < Hi(i - 2)) &&
                  (Cl(i - 1) < Op(i - 1)) &&
                  (Cl(i) > Op(i)) && (Hi(i) > Hi(i - 2));
   bool bearPat = (Cl(i - 2) > Op(i - 2)) &&
                  (Hi(i - 1) > Hi(i - 2)) && (Lo(i - 1) > Lo(i - 2)) &&
                  (Cl(i - 1) > Op(i - 1)) &&
                  (Cl(i) < Op(i)) && (Lo(i) < Lo(i - 2));

   bool bullishReversal = InpShow3BR && bullPat && bullTrend;
   bool bearishReversal = InpShow3BR && bearPat && bearTrend;

   if(bullishReversal)
     {
      g_bull3brProcess = true;
      g_bull3brEvent   = true;
      g_bull3brLnAT    = Hi(i - 2);                            // top line level
      g_bull3brLnAB    = MathMin(Lo(i - 1), Lo(i));            // bottom line level
      g_bull3brHigh    = g_bull3brLnAB;                        // S/R "Level"
     }
   if(g_bull3brProcess)
     {
      if(Cl(i - 1) > g_bull3brLnAT)
        {
         g_bull3brConfirm = true;   // close[1] above the pattern high
         g_bull3brProcess = false;
        }
      if(Cl(i - 1) < g_bull3brLnAB || bearishReversal)
         g_bull3brProcess = false; // pattern failed
     }

   if(bearishReversal)
     {
      g_bear3brProcess = true;
      g_bear3brEvent   = true;
      g_bear3brLnSB    = Lo(i - 2);                            // bottom line level
      g_bear3brLnST    = MathMax(Hi(i - 1), Hi(i));            // top line level
      g_bear3brLow     = g_bear3brLnST;                        // S/R "Level"
     }
   if(g_bear3brProcess)
     {
      if(Cl(i - 1) > g_bear3brLnST || bullishReversal)
         g_bear3brProcess = false; // pattern failed
      if(Cl(i - 1) < g_bear3brLnSB)
        {
         g_bear3brConfirm = true;   // close[1] below the pattern low
         g_bear3brProcess = false;
        }
     }
  }

//+------------------------------------------------------------------+
//| Reversal Signals step (momentum count + S/R, Pine port)           |
//+------------------------------------------------------------------+
void StepRS(int i)
  {
   if(i < 4)
      return;
   bool conRS = Cl(i) < Cl(i - 4);
   if(conRS)
     {
      g_bSCRS = (g_bSCRS == 9) ? 1 : g_bSCRS + 1;
      g_sSCRS = 0;
     }
   else
     {
      g_sSCRS = (g_sSCRS == 9) ? 1 : g_sSCRS + 1;
      g_bSCRS = 0;
     }
   g_showBullMom = (g_bSCRS == 9);
   g_showBearMom = (g_sSCRS == 9);

   // ta.highest(9)/ta.lowest(9) include the current bar i
   // (window clamped during warmup, like Pine)
   int w = MathMin(9, i + 1);
   double hh = Hi(i), ll = Lo(i);
   for(int k = 1; k < w; k++)
     {
      hh = MathMax(hh, Hi(i - k));
      ll = MathMin(ll, Lo(i - k));
     }
   if(g_bSCRS == 9)
     {
      g_bSRRS  = hh;
      g_bSRRSOn = true;
     }
   else if(g_bSRRSOn && Cl(i) > g_bSRRS)
      g_bSRRSOn = false;   // Pine: na

   if(g_sSCRS == 9)
     {
      g_sSSRS  = ll;
      g_sSSRSOn = true;
     }
   else if(g_sSSRSOn && Cl(i) < g_sSSRS)
      g_sSSRSOn = false;
  }

//+------------------------------------------------------------------+
//| OB / FVG retest detection (latest closed bar)                     |
//+------------------------------------------------------------------+
void CheckRetests()
  {
   int last = g_n - 1;                 // latest closed bar (forward index)
   double lo0 = Lo(last), cl0 = Cl(last), hi0 = Hi(last);
   for(int k = ArraySize(g_fvgs) - 1; k >= 0; k--)
     {
      if(g_fvgs[k].isbull && !g_fvgBullRetest)
         g_fvgBullRetest = (lo0 <= g_fvgs[k].max && cl0 >= g_fvgs[k].min);
      else if(!g_fvgs[k].isbull && !g_fvgBearRetest)
         g_fvgBearRetest = (hi0 >= g_fvgs[k].min && cl0 <= g_fvgs[k].max);
     }
   for(int k = ArraySize(g_bullObs) - 1; k >= 0; k--)
      if(!g_obBullRetest)
         g_obBullRetest = (lo0 <= g_bullObs[k].top && cl0 >= g_bullObs[k].btm);
   for(int k = ArraySize(g_bearObs) - 1; k >= 0; k--)
      if(!g_obBearRetest)
         g_obBearRetest = (hi0 >= g_bearObs[k].btm && cl0 <= g_bearObs[k].top);
  }

//+------------------------------------------------------------------+
//| Full replay over the closed-bar window (deterministic, no repaint)|
//+------------------------------------------------------------------+
void Replay()
  {
   ReplayReset();

   int n = g_n;

   // hull source + hull series
   ArrayResize(g_srcHull, n);
   for(int i = 0; i < n; i++)
      g_srcHull[i] = (InpHullSrc == UT_SRC_HA)
                     ? (Op(i) + Hi(i) + Lo(i) + Cl(i)) / 4.0
                     : Cl(i);
   CalcHullArray(g_srcHull, g_hullArr);

   // 3BR MA cloud series (from close, like the Pine movingAverage3BR)
   ArrayResize(g_closes, n);
   for(int i = 0; i < n; i++)
      g_closes[i] = g_r[i].close;
   bool useCloud = (InpShow3BR && Inp3BRTrendType == T3BR_MACLOUD);
   if(useCloud)
     {
      CalcMAArray(g_closes, Inp3BRMaFast, Inp3BRMaType, g_maF);
      CalcMAArray(g_closes, Inp3BRMaSlow, Inp3BRMaType, g_maS);
     }

   // supertrend series for the 3BR trend filter
   bool useST = (InpShow3BR && Inp3BRTrendType == T3BR_SUPERTREND);
   if(useST)
      CalcSupertrend(Inp3BRStAtr, Inp3BRStFactor, g_stDir);

   bool useDonchian = (InpShow3BR && Inp3BRTrendType == T3BR_DONCHIAN);
   double dcUpPrev = 0, dcDnPrev = 0;

   for(int i = 0; i < n; i++)
     {
      StepRS(i);
      StepStructure(g_ext, InpExtSens, i);
      StepStructure(g_int, InpIntSens, i);
      StepUT(i);
      StepFVG(i);
      StepOB(i);

      // 3BR trend filter, evaluated at bar i (no lookahead)
      bool bt = true, br = true;
      if(useCloud)
        {
         if(Inp3BRAligned)
           {
            bt = (Cl(i) > g_maF[i] && g_maF[i] > g_maS[i]);
            br = (Cl(i) < g_maF[i] && g_maF[i] < g_maS[i]);
           }
         else
           {
            bt = (Cl(i) < g_maF[i] && g_maF[i] < g_maS[i]);
            br = (Cl(i) > g_maF[i] && g_maF[i] > g_maS[i]);
           }
        }
      else if(useST)
        {
         int d = g_stDir[i];   // -1 = up, +1 = down
         if(Inp3BRAligned)
           {
            bt = (d < 0);
            br = (d > 0);
           }
         else
           {
            bt = (d > 0);
            br = (d < 0);
           }
        }
      else if(useDonchian && i >= Inp3BRDcLength)
        {
         // Donchian on close over Inp3BRDcLength bars ending at bar i
         double up = -DBL_MAX, dn = DBL_MAX;
         for(int k = 0; k < Inp3BRDcLength; k++)
           {
            up = MathMax(up, Cl(i - k));
            dn = MathMin(dn, Cl(i - k));
           }
         if(dcUpPrev != 0)
           {
            if(up > dcUpPrev)
               g_3brOs = 1;
            else if(dn < dcDnPrev)
               g_3brOs = 0;
           }
         dcUpPrev = up;
         dcDnPrev = dn;
         if(Inp3BRAligned)
           {
            bt = (g_3brOs == 1);
            br = (g_3brOs == 0);
           }
         else
           {
            bt = (g_3brOs == 0);
            br = (g_3brOs == 1);
           }
        }

      Step3BR(i, bt, br);
     }

   // final-bar derived values
   g_hull      = g_hullArr[n - 1];
   g_hullPrev2 = (n >= 3) ? g_hullArr[n - 3] : g_hull;
   g_hullUp    = (g_hull > g_hullPrev2);

   CheckRetests();
  }

//+------------------------------------------------------------------+
//| Position helpers (FTTestCore conventions)                         |
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

void ActOnSignal(ENUM_ORDER_TYPE type, double sl, double tp)
  {
   ulong t = FindPosition();
   if(t != 0)
     {
      long ptype = PositionGetInteger(POSITION_TYPE);
      if((type == ORDER_TYPE_BUY && ptype == POSITION_TYPE_BUY) ||
         (type == ORDER_TYPE_SELL && ptype == POSITION_TYPE_SELL))
         return; // already aligned, hold
      bool ok = trade.PositionClose(t);
      Print(Label(), " CLOSE #", t, " (reverse) ok=", ok, " ret=", trade.ResultRetcode());
     }
   OpenMarket(type, sl, tp);
  }

//+------------------------------------------------------------------+
//| Trailing SL twin (same rules as FTTestCore)                       |
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
//| Confluence scoring + trade decision (latest closed bar)           |
//+------------------------------------------------------------------+
void TradeOnSignals()
  {
   int bullScore = 0, bearScore = 0, bullHard = 0, bearHard = 0;

   // UT Bot (hard)
   if(g_utBuy)  { bullScore++; bullHard++; }
   if(g_utSell) { bearScore++; bearHard++; }

   // External structure break (hard; CHoCH-only filter optional)
   if(g_ext.evBull && (!InpTradeCHoCHOnly || g_ext.kindBull == 1))
     { bullScore++; bullHard++; }
   if(g_ext.evBear && (!InpTradeCHoCHOnly || g_ext.kindBear == 1))
     { bearScore++; bearHard++; }

   // Internal structure break (soft)
   if(g_int.evBull) bullScore++;
   if(g_int.evBear) bearScore++;

   // Three Bar Reversal (hard: detection or confirmation)
   if(InpShow3BR && (g_bull3brEvent || g_bull3brConfirm))
     { bullScore++; bullHard++; }
   if(InpShow3BR && (g_bear3brEvent || g_bear3brConfirm))
     { bearScore++; bearHard++; }

   // Momentum count (soft)
   if(InpShowRS && g_showBullMom) bullScore++;
   if(InpShowRS && g_showBearMom) bearScore++;

   // FVG / OB retests (hard, optional)
   if(InpShowFVG && InpTradeFVGRetest && g_fvgBullRetest)
     { bullScore++; bullHard++; }
   if(InpShowFVG && InpTradeFVGRetest && g_fvgBearRetest)
     { bearScore++; bearHard++; }
   if(InpShowOB && InpTradeOBRetest && g_obBullRetest)
     { bullScore++; bullHard++; }
   if(InpShowOB && InpTradeOBRetest && g_obBearRetest)
     { bearScore++; bearHard++; }

   bool wantBuy = false, wantSell = false;
   if(InpTradingMode == TRADE_UT_ONLY)
     {
      wantBuy  = g_utBuy;
      wantSell = g_utSell;
     }
   else if(InpTradingMode == TRADE_CONFLUENCE)
     {
      wantBuy  = (bullScore >= InpMinConfluence && bullScore > bearScore && bullHard > 0);
      wantSell = (bearScore >= InpMinConfluence && bearScore > bullScore && bearHard > 0);
     }

   if(!wantBuy && !wantSell)
      return;

   // Hull trend filter (optional)
   if(InpUseHullFilter)
     {
      if(wantBuy && !g_hullUp)
         return;
      if(wantSell && g_hullUp)
         return;
     }

   double px = Cl(g_n - 1);
   if(wantBuy)
      ActOnSignal(ORDER_TYPE_BUY,  px - InpSlAtrMult * g_atr, px + InpTpAtrMult * g_atr);
   else
      ActOnSignal(ORDER_TYPE_SELL, px + InpSlAtrMult * g_atr, px - InpTpAtrMult * g_atr);
  }

//+------------------------------------------------------------------+
//| Chart dashboard                                                   |
//+------------------------------------------------------------------+
void Dashboard()
  {
   string mode = (InpTradingMode == TRADE_UT_ONLY) ? "UT only" :
                 (InpTradingMode == TRADE_CONFLUENCE) ? "Confluence" : "Signals only";
   string hull = g_hullUp ? "UP" : "DOWN";
   string extB = g_ext.evBull ? (g_ext.kindBull == 1 ? "CHoCH" : "BoS") : "-";
   string extS = g_ext.evBear ? (g_ext.kindBear == 1 ? "CHoCH" : "BoS") : "-";
   string ut   = (g_utPos == 1) ? "LONG" : (g_utPos == -1) ? "SHORT" : "FLAT";
   int bullScore = (g_utBuy ? 1 : 0) + (g_ext.evBull ? 1 : 0) + (g_int.evBull ? 1 : 0) +
                   ((InpShow3BR && (g_bull3brEvent || g_bull3brConfirm)) ? 1 : 0) +
                   ((InpShowRS && g_showBullMom) ? 1 : 0);
   int bearScore = (g_utSell ? 1 : 0) + (g_ext.evBear ? 1 : 0) + (g_int.evBear ? 1 : 0) +
                   ((InpShow3BR && (g_bear3brEvent || g_bear3brConfirm)) ? 1 : 0) +
                   ((InpShowRS && g_showBearMom) ? 1 : 0);
   Comment(StringFormat(
      "AETHER FLOW %d  [%s %s  %s]\n"
      "UT Bot: %s  buy=%s sell=%s\n"
      "Hull: %s   SwingHi: %s  SwingLo: %s\n"
      "Struct: bull %s / bear %s   IntBull %d IntBear %d\n"
      "FVG: bull %d (mit %d)  bear %d (mit %d)   retest b%d s%d\n"
      "OB: bull %d (mit %d)  bear %d (mit %d)   retest b%d s%d\n"
      "3BR: bull ev=%s conf=%s  bear ev=%s conf=%s\n"
      "Momentum: b%d s%d   Confluence: bull %d / bear %d   ATR=%s",
      InpMagic, _Symbol, EnumToString(InpTimeframe), mode,
      ut, g_utBuy ? "Y" : "n", g_utSell ? "Y" : "n",
      hull, DoubleToString(g_ext.upAxis, _Digits), DoubleToString(g_ext.dnAxis, _Digits),
      extB, extS, g_int.evBull, g_int.evBear,
      g_fvgBullCount, g_fvgBullMit, g_fvgBearCount, g_fvgBearMit,
      g_fvgBullRetest ? 1 : 0, g_fvgBearRetest ? 1 : 0,
      g_obBullCount, g_obBullMit, g_obBearCount, g_obBearMit,
      g_obBullRetest ? 1 : 0, g_obBearRetest ? 1 : 0,
      g_bull3brEvent ? "Y" : "n", g_bull3brConfirm ? "Y" : "n",
      g_bear3brEvent ? "Y" : "n", g_bear3brConfirm ? "Y" : "n",
      g_bSCRS, g_sSCRS, bullScore, bearScore,
      DoubleToString(g_atr, _Digits)));
  }

//+------------------------------------------------------------------+
//| Stuck-stop guard: the broker server can lag badly (2026-09-29:    |
//| p90 order ack 60s+), leaving price THROUGH an SL/TP with nothing  |
//| executing. Re-send the stop levels (pulsed 1 point further from   |
//| price so the modify is a real change) to re-arm the server stop;  |
//| if still stuck after InpStuckGiveupSec, close market. Single-slot |
//| state: this EA holds at most one position.                        |
//+------------------------------------------------------------------+
input group             "Stuck-stop guard"
input bool   InpStuckGuard      = true;  // Re-trigger stuck SL/TP
input int    InpStuckThreshPts  = 50;    // Min breach beyond stop (points)
input int    InpStuckPersistSec = 30;    // Breach persistence before re-trigger (s)
input int    InpStuckGiveupSec  = 180;   // Persist this long -> market close (s)

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
         break;
        }
     }

   static ulong    s_ticket  = 0;
   static datetime s_since   = 0;
   static int      s_resent  = 0;
   static datetime s_lastTry = 0;
   if(ticket == 0)
     {
      s_ticket = 0; s_since = 0; s_resent = 0; s_lastTry = 0;
      return;
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
   // is the only valid action (2026-09-30 fix, mirrors FTTestCore)
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

//+------------------------------------------------------------------+
//| Time stop: close any position older than InpATimeStop bars.       |
//| 0 = off (matches the uncapped backtest). On H4 the cap is set to  |
//| 12 bars (48h): uncapped H4 holds are the bleed (60d backtest     |
//| fixed -$408 uncapped vs +$97 capped, trail +$95 vs +$411).       |
//+------------------------------------------------------------------+
void TimeStop()
  {
   if(InpATimeStop <= 0)
      return;
   ulong t = FindPosition();
   if(t == 0)
      return;
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
   if(TimeCurrent() - opened >= InpATimeStop * PeriodSeconds(InpTimeframe))
     {
      if(trade.PositionClose(t))
         Print(Label(), " TIME-STOP close after ", InpATimeStop, " bars");
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   TrailStop(); // every tick so trailing reacts to live price
   StuckStopGuard(); // re-trigger SL/TP the broker left unexecuted
   TimeStop(); // max-hold cap (H4 = 12 bars)

   MqlRates r[];
   int copied = CopyRates(_Symbol, InpTimeframe, 1, 600, r);
   if(copied < 300)
      return;                      // warmup: all engines need enough history
   if(r[copied - 1].time == g_lastBar)
      return;                      // wait for a new closed bar
   g_lastBar = r[copied - 1].time;

   ArrayResize(g_r, copied);
   for(int i = 0; i < copied; i++)
      g_r[i] = r[i];
   g_n = copied;

   g_atr = CalcATR(g_r, 14);
   if(g_atr <= 0)
      return;

   Replay();
   TradeOnSignals();
   Dashboard();
  }
//+------------------------------------------------------------------+
