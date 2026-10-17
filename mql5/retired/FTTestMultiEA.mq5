//+------------------------------------------------------------------+
//| FTTestMultiEA.mq5                                                 |
//| Forward-test EA, MULTI-SYMBOL: 4 FX pairs x 9 strategies x        |
//| fixed-SL / trailing-SL twins (72 streams) from ONE chart.         |
//| Mirrors scripts/forward_test.py so results stay comparable.       |
//|                                                                   |
//| Why one chart: the 1 GB VPS cannot carry 70 EA charts; a single   |
//| instance loops all symbols on a 5s timer, independent of chart    |
//| ticks. XAUUSD keeps its 14 dedicated FTTestEA charts.             |
//|                                                                   |
//| Magics (python runner base +20000 fixed / +30000 trailing):       |
//|   EURUSD 9310xx/9410xx  GBPUSD 9320xx/9420xx                      |
//|   USDJPY 9330xx/9430xx  AUDUSD 9340xx/9440xx                      |
//| where xx = 1..7 per strategy (same order as the runner).          |
//|                                                                   |
//| Strategies (same rules as the Python forward test):               |
//|   breakout  Donchian-20 breakout            (M15)                 |
//|   meanrev   RSI(14) fade                    (M15)                 |
//|   macross   EMA9/EMA21 cross                (M30)                 |
//|   straddle  dual stops around 4-bar range   (H1, per hour)        |
//|   smc       liquidity sweep + reversal      (M15)                 |
//|   london    Asian-range breakout            (M15, per day)        |
//|   squeeze   Bollinger-in-Keltner expansion  (M15)                 |
//|   profile   TPO value-area rotation/breakout (M15) -- chart21/22   |
//|   orderflow delta imbalance/absorption      (M1)  -- chart23/24   |
//|                                                                   |
//| profile/orderflow notes: XAUUSD runs them on dedicated charts     |
//| (930008/940008, 930009/940009). The FX versions here use the same |
//| rules; orderflow synthesizes per-minute delta from bar CLV (close |
//| location value) instead of tick flags -- the M1 chart holds no    |
//| tick history, and bar-CLV models the delta DIRECTION faithfully   |
//| while smoothing intrabar spikes.                                  |
//+------------------------------------------------------------------+
#property copyright "meta-trader-mcp forward test"
#property version   "1.00"
#property strict
#include <Trade\Trade.mqh>

#define SYM_COUNT 4
#define STRAT_COUNT 9

input group             "Core"
input string            InpSymbols      = "EURUSD,GBPUSD,USDJPY,AUDUSD"; // Symbols (comma-separated)
input double            InpLots         = 0.01;        // Lot size (fixed)
input int               InpBaseMagic    = 931000;      // Base magic (931000=EUR; +1000 per next symbol; 0 = refuse)
input int               InpSweepSec     = 300;         // Sweep interval (s); 5 live, 300 in Strategy Tester

input group             "Market Profile (strategy 7)"
input int               InpProfileBars   = 96;   // Profile lookback (bars)
input int               InpProfileBins   = 24;   // Price bins
input double            InpValueAreaPct  = 70.0; // Value area (% of TPOs)

input group             "Order Flow (strategy 8)"
input int               InpOFBars        = 30;   // Flow window (minutes)
input double            InpOFImbRatio    = 3.0;  // Delta imbalance ratio
input double            InpOFMinCum      = 0.6;  // Min cumulative-delta share

input group             "Trailing SL (applies to the -T twin magic)"
input double            InpTrailActAtr  = 1.0;         // Activate after (x ATR)
input double            InpTrailDistAtr = 1.2;         // Trail distance (x ATR)
input double            InpTrailStepAtr = 0.3;         // Min SL move (x ATR)

input group             "Safety"
input bool              InpAllowReal    = false;       // Allow REAL accounts
input int               InpDeviationPts = 50;          // Max slippage (points)
input bool              InpMeanrevEnabled = false;     // Run meanrev on FX?
                        // (suspended 9/28: 30d backtest PF 0.48-0.85 on 3 of
                        //  4 FX pairs, -4.60 total; XAU keeps its charts)

CTrade  trade;
string  g_syms[SYM_COUNT];
int     g_symCount = 0;

// strategy table: name, mode(0=signal,1=hourly dual,2=daily dual), timeframe
int      g_mode[STRAT_COUNT];
string   g_sname[STRAT_COUNT];
ENUM_TIMEFRAMES g_tf[STRAT_COUNT];

// per (symbol, strategy) state
datetime g_lastBar[SYM_COUNT][STRAT_COUNT];
double   g_atr[SYM_COUNT][STRAT_COUNT];
// Champion exit style from the 30d trailing-vs-fixed verdict matrix
// (scripts/backtest_trailing_check.py): bit st set = trailing WON that
// (symbol, strategy) slot; where fixed won, the -T twin holds a static SL.
// bit0=breakout 1=meanrev 2=macross 3=straddle 4=smc 5=london 6=squeeze
// 7=profile 8=orderflow (30d FX backtest verdict: fixed won -> bits clear)
int g_trailWin[SYM_COUNT];
// per (symbol, strategy, twin) dual-stop state -- mirrors the runner's
// _run_dual: derived from LIVE orders so failed sends retry on the next sweep
datetime g_dualPeriod[SYM_COUNT][STRAT_COUNT][2];
bool     g_dualFired[SYM_COUNT][STRAT_COUNT][2];
bool     g_skipBuy[SYM_COUNT][STRAT_COUNT][2];
bool     g_skipSell[SYM_COUNT][STRAT_COUNT][2];

// London-open breakout session bounds in SERVER hours (mirrors forward_test.py)
#define LONDON_START_HOUR 11
#define LONDON_END_HOUR   17

//+------------------------------------------------------------------+
int StratMode(int s)   { return(g_mode[s]); }
string StratName(int s){ return(g_sname[s]); }

int BaseMagic(int si, int st)  { return(InpBaseMagic + si * 1000 + st + 1); }
int TwinMagic(int si, int st)  { return(BaseMagic(si, st) + 10000); }

string Label(string sym, int magic)
  {
   return(StringFormat("%s %d", StreamName(sym, magic), magic));
  }

string StreamName(string sym, int magic)
  {
   bool trail = (magic >= InpBaseMagic + 10000);
   int m = trail ? magic - 10000 : magic;
   int si = (m - InpBaseMagic) / 1000;
   int st = (m - InpBaseMagic) % 1000 - 1;
   if(si < 0 || si >= SYM_COUNT || st < 0 || st >= STRAT_COUNT)
      return("?");
   string code = (StringSubstr(sym, 0, 3) == "USD") ? StringSubstr(sym, 3, 3)
                                                    : StringSubstr(sym, 0, 3);
   return(g_sname[st] + "-" + code + (trail ? "-T" : ""));
  }

//+------------------------------------------------------------------+
//| Safety rail: demo-only unless explicitly allowed                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   // strategy table (order must match the runner: 1..7)
   g_sname[0]="breakout"; g_mode[0]=0; g_tf[0]=PERIOD_M15;
   g_sname[1]="meanrev";  g_mode[1]=0; g_tf[1]=PERIOD_M15;
   g_sname[2]="macross";  g_mode[2]=0; g_tf[2]=PERIOD_M30;
   g_sname[3]="straddle"; g_mode[3]=1; g_tf[3]=PERIOD_H1;
   g_sname[4]="smc";      g_mode[4]=0; g_tf[4]=PERIOD_M15;
   g_sname[5]="london";   g_mode[5]=2; g_tf[5]=PERIOD_M15;
   g_sname[6]="squeeze";  g_mode[6]=0; g_tf[6]=PERIOD_M15;
   g_sname[7]="profile";  g_mode[7]=0; g_tf[7]=PERIOD_M15;
   g_sname[8]="orderflow"; g_mode[8]=0; g_tf[8]=PERIOD_M1;

   if(InpBaseMagic <= 0)
     {
      Print("REFUSING: InpBaseMagic must be set explicitly (931000 = EUR base).");
      return(INIT_FAILED);
     }
   string parts[];
   int n = StringSplit(InpSymbols, ',', parts);
   if(n < 1 || n > SYM_COUNT)
     {
      Print("REFUSING: InpSymbols must list 1..", SYM_COUNT, " comma-separated symbols.");
      return(INIT_FAILED);
     }
   for(int i = 0; i < n; i++)
     {
      StringTrimLeft(parts[i]);
      StringTrimRight(parts[i]);
      if(!SymbolSelect(parts[i], true))
        {
         Print("REFUSING: symbol not found: ", parts[i]);
         return(INIT_FAILED);
        }
      g_syms[i] = parts[i];
     }
   g_symCount = n;

   ENUM_ACCOUNT_TRADE_MODE mode =
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_REAL && !InpAllowReal)
     {
      Print("REFUSING: real-money account and InpAllowReal=false. ",
            "This EA is demo-only unless you deliberately enable it.");
      return(INIT_FAILED);
     }
   // verdict matrix (matches scripts/forward_test.py WINNER): trailing only
   // manages the -T twin where the backtest showed it improves profit
   // profile(7)/orderflow(8) FX verdicts from backtest_profile_orderflow.py
   // (30d): fixed won every FX slot -> bits 7/8 stay clear; XAUUSD runs its
   // own dedicated charts where the 30d verdict favored trailing.
   g_trailWin[0] = 80;  // EURUSD: smc(16) + squeeze(64)
   g_trailWin[1] = 5;   // GBPUSD: breakout(1) + macross(4)
   g_trailWin[2] = 69;  // USDJPY: breakout(1) + macross(4) + squeeze(64)
   g_trailWin[3] = 84;  // AUDUSD: macross(4) + smc(16) + squeeze(64)

   trade.SetDeviationInPoints(InpDeviationPts);
   trade.SetExpertMagicNumber(0); // magic is set per request below
   Print("FTTestMulti started: ", g_symCount, " symbols x ", STRAT_COUNT,
         " strategies x 2 twins (", g_symCount * STRAT_COUNT * 2,
         " streams incl. profile + orderflow), base=", InpBaseMagic, " lots=", InpLots,
         " meanrev=", InpMeanrevEnabled ? "ON" : "SUSPENDED");
   for(int i = 0; i < g_symCount; i++)
      Print("  ", g_syms[i], " base=", BaseMagic(i, 0), "..", BaseMagic(i, STRAT_COUNT - 1));
   Comment("FTTestMulti ", IntegerToString(InpBaseMagic), "  ",
           g_symCount, " symbols x ", STRAT_COUNT, " strategies x 2 twins  [multi]");
   // the whole engine runs on one sweep (5s live; wider in the Strategy
   // Tester so a 30-day backtest does not simulate 500k+ sweeps)
   EventSetTimer(InpSweepSec < 1 ? 1 : InpSweepSec);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

//+------------------------------------------------------------------+
//| Math helpers (closed bars only: r[0]=oldest ... r[n-1]=last)      |
//+------------------------------------------------------------------+
int ClosedBarsOf(string sym, ENUM_TIMEFRAMES tf, int n, MqlRates &r[])
  {
   return(CopyRates(sym, tf, 1, n, r));
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
//| Position/order helpers (parameterized by symbol + magic)          |
//+------------------------------------------------------------------+
ulong PosOf(string sym, int magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL) != sym)
         continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      return(t);
     }
   return(0);
  }

bool OpenMarket(string sym, int magic, ENUM_ORDER_TYPE type, double sl, double tp)
  {
   trade.SetExpertMagicNumber(magic);
   double price = (type == ORDER_TYPE_BUY) ?
      SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   bool ok = trade.PositionOpen(sym, type, InpLots, price, sl, tp,
                                Label(sym, magic));
   Print(Label(sym, magic), " OPEN ", (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
         " ", InpLots, " @ ", price, " sl=", sl, " tp=", tp, " ok=", ok,
         " ret=", trade.ResultRetcode());
   return(ok);
  }

void CloseMine(string sym, int magic)
  {
   ulong t = PosOf(sym, magic);
   if(t != 0)
     {
      trade.SetExpertMagicNumber(magic);
      bool ok = trade.PositionClose(t);
      Print(Label(sym, magic), " CLOSE #", t, " ok=", ok, " ret=", trade.ResultRetcode());
     }
  }

void DeletePendingsOf(string sym, int magic)
  {
   trade.SetExpertMagicNumber(magic);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0)          // stale index -- see FTTestCore.mqh DeleteMyPendings
         continue;
      if(OrderGetString(ORDER_SYMBOL) != sym)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != magic)
         continue;
      trade.OrderDelete(t);
     }
  }

bool PendSideOf(string sym, int magic, ENUM_ORDER_TYPE type)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL) != sym)
         continue;
      if((int)OrderGetInteger(ORDER_MAGIC) != magic)
         continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE) == type)
         return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Signal-mode strategies: hold if aligned, reverse if opposed.      |
//| One signal drives BOTH twins (fixed + trailing), like the runner. |
//+------------------------------------------------------------------+
void ActOnSignal(int si, int st, ENUM_ORDER_TYPE type, double sl, double tp)
  {
   string sym = g_syms[si];
   for(int twin = 0; twin < 2; twin++)
     {
      int magic = (twin == 0) ? BaseMagic(si, st) : TwinMagic(si, st);
      ulong t = PosOf(sym, magic);
      if(t != 0)
        {
         long ptype = PositionGetInteger(POSITION_TYPE);
         if((type == ORDER_TYPE_BUY && ptype == POSITION_TYPE_BUY) ||
            (type == ORDER_TYPE_SELL && ptype == POSITION_TYPE_SELL))
            continue; // already aligned, hold
         CloseMine(sym, magic); // opposite signal -> reverse
        }
      OpenMarket(sym, magic, type, sl, tp);
     }
  }

//+------------------------------------------------------------------+
//| Dual-stop arming (straddle/london), retry-safe per twin           |
//+------------------------------------------------------------------+
void ArmDual(int si, int st, int twin, datetime period,
             bool haveLevels, double buy_stop, double sell_stop, double a)
  {
   string sym = g_syms[si];
   int magic = (twin == 0) ? BaseMagic(si, st) : TwinMagic(si, st);
   if(period != g_dualPeriod[si][st][twin])
     {
      g_dualPeriod[si][st][twin] = period;
      g_dualFired[si][st][twin]  = false;
      g_skipBuy[si][st][twin]    = false;
      g_skipSell[si][st][twin]   = false;
      DeletePendingsOf(sym, magic); // new period: clear leftovers
     }
   if(PosOf(sym, magic) != 0)
     {
      g_dualFired[si][st][twin] = true;
      DeletePendingsOf(sym, magic); // one side filled -> kill the far one
      return;
     }
   if(g_dualFired[si][st][twin])
      return; // already traded this period
   if(!haveLevels)
      return;
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   // stops must sit on the correct side of the market or the broker rejects;
   // a failed send is retried on the next sweep (5s)
   if(!PendSideOf(sym, magic, ORDER_TYPE_BUY_STOP) && !g_skipBuy[si][st][twin])
     {
      if(buy_stop > ask)
        {
         trade.SetExpertMagicNumber(magic);
         if(!trade.BuyStop(InpLots, buy_stop, sym, buy_stop - a, buy_stop + a,
                           ORDER_TIME_GTC, 0, Label(sym, magic)))
            Print(Label(sym, magic), " buy stop FAILED ret=", trade.ResultRetcode(),
                  " (will retry next sweep)");
        }
      else
        {
         Print(Label(sym, magic), " skip buy stop (price already beyond range)");
         g_skipBuy[si][st][twin] = true;
        }
     }
   if(!PendSideOf(sym, magic, ORDER_TYPE_SELL_STOP) && !g_skipSell[si][st][twin])
     {
      if(sell_stop < bid)
        {
         trade.SetExpertMagicNumber(magic);
         if(!trade.SellStop(InpLots, sell_stop, sym, sell_stop + a, sell_stop - a,
                            ORDER_TIME_GTC, 0, Label(sym, magic)))
            Print(Label(sym, magic), " sell stop FAILED ret=", trade.ResultRetcode(),
                  " (will retry next sweep)");
        }
      else
        {
         Print(Label(sym, magic), " skip sell stop (price already beyond range)");
         g_skipSell[si][st][twin] = true;
        }
     }
  }

//+------------------------------------------------------------------+
//| Signals (mirroring scripts/forward_test.py)                       |
//+------------------------------------------------------------------+
void SigBreakout(const MqlRates &r[], double a, int si, int st)
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
      ActOnSignal(si, st, ORDER_TYPE_BUY, close - 2 * a, close + 3 * a);
   else if(close < lo)
      ActOnSignal(si, st, ORDER_TYPE_SELL, close + 2 * a, close - 3 * a);
  }

void SigMeanrev(const MqlRates &r[], double a, int si, int st)
  {
   int bars = ArraySize(r);
   if(bars < 20 || a <= 0)
      return;
   double rs = CalcRSI(r, 14);
   if(rs < 0)
      return;
   double px = r[bars - 1].close;
   if(rs < 25)
      ActOnSignal(si, st, ORDER_TYPE_BUY, px - 1.5 * a, px + 1.0 * a);
   else if(rs > 75)
      ActOnSignal(si, st, ORDER_TYPE_SELL, px + 1.5 * a, px - 1.0 * a);
  }

void SigMacross(const MqlRates &r[], double a, int si, int st)
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
      ActOnSignal(si, st, ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(fp >= sp && f < s)
      ActOnSignal(si, st, ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

void SigSMC(const MqlRates &r[], double a, int si, int st)
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

   if(b.low < lo && b.close > lo && small_body && lower_wick > 0.5 * range)
     {
      double entry = b.close;
      double sl = b.low - 0.1 * a;
      double risk = entry - sl;
      if(risk > 0)
         ActOnSignal(si, st, ORDER_TYPE_BUY, sl, entry + 3 * risk);
      return;
     }
   if(b.high > hi && b.close < hi && small_body && upper_wick > 0.5 * range)
     {
      double entry = b.close;
      double sl = b.high + 0.1 * a;
      double risk = sl - entry;
      if(risk > 0)
         ActOnSignal(si, st, ORDER_TYPE_SELL, sl, entry - 3 * risk);
     }
  }

void SigSqueeze(const MqlRates &r[], double a, int si, int st)
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
      ActOnSignal(si, st, ORDER_TYPE_BUY, px - 2 * a, px + 3 * a);
   else if(px < mid - 2 * sd)
      ActOnSignal(si, st, ORDER_TYPE_SELL, px + 2 * a, px - 3 * a);
  }

//+------------------------------------------------------------------+
//| Profile: TPO value-area edges over the last InpProfileBars bars    |
//| (identical math to FTTestCore's MarketProfile/SigProfile).         |
//+------------------------------------------------------------------+
bool MultiProfile(const MqlRates &r[], int bins, double &poc, double &vah, double &val)
  {
   int bars = ArraySize(r);
   if(bars < 20 || bins < 4)
      return(false);
   int n = MathMin(bars, InpProfileBars);
   int i0 = bars - n;
   double lo = r[i0].low, hi = r[i0].high;
   for(int i = i0 + 1; i < bars; i++)
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
   for(int i = i0; i < bars; i++)
     {
      double bl = MathMin(r[i].open, r[i].close);   // body = time at price
      double bh = MathMax(r[i].open, r[i].close);
      if(bh <= bl)
         bh = bl + step;                            // doji: one bin
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
      int dn = (loI > 0) ? tpo[loI - 1] : -1;
      int up = (hiI < bins - 1) ? tpo[hiI + 1] : -1;
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

void SigProfileMulti(const MqlRates &r[], double a, int si, int st)
  {
   int bars = ArraySize(r);
   if(bars < 20 || a <= 0)
      return;
   double poc, vah, val;
   if(!MultiProfile(r, InpProfileBins, poc, vah, val))
      return;
   double c = r[bars - 1].close;
   if(c > vah + 0.5 * a)
      ActOnSignal(si, st, ORDER_TYPE_BUY, c - 1.5 * a, c + 3.0 * a);
   else if(c < val - 0.5 * a)
      ActOnSignal(si, st, ORDER_TYPE_SELL, c + 1.5 * a, c - 3.0 * a);
   else if(c > vah)
      ActOnSignal(si, st, ORDER_TYPE_SELL, c + 1.2 * a, poc);
   else if(c < val)
      ActOnSignal(si, st, ORDER_TYPE_BUY, c - 1.2 * a, poc);
  }

//+------------------------------------------------------------------+
//| Order flow (FX version): per-minute delta synthesized from bar     |
//| close-location value (the M1 chart has no tick history; CLV models |
//| the delta DIRECTION faithfully, smoothing intrabar spikes).        |
//+------------------------------------------------------------------+
void SigOrderflowMulti(const MqlRates &r[], double a, int si, int st)
  {
   int bars = ArraySize(r);
   if(bars < InpOFBars + 2 || a <= 0)
      return;
   double delta[];
   ArrayResize(delta, InpOFBars);
   ArrayInitialize(delta, 0.0);
   double prev_close = r[bars - InpOFBars - 1].close;
   for(int k = 0; k < InpOFBars; k++)
     {
      MqlRates b = r[bars - InpOFBars + k];
      double rng = b.high - b.low;
      double clv = (rng > 0) ? (2.0 * b.close - b.high - b.low) / rng : 0.0;
      double tilt = 0.0;
      if(prev_close > 0 && rng > 0)
         tilt = MathMax(-0.5, MathMin(0.5, (b.close - prev_close) / rng));
      delta[k] = (clv + tilt) * (b.tick_volume > 0 ? (double)b.tick_volume : 1.0);
      prev_close = b.close;
     }
   double cum = 0.0, absSum = 0.0;
   for(int k = 0; k < InpOFBars; k++)
     {
      cum += delta[k];
      absSum += MathAbs(delta[k]);
     }
   if(absSum <= 0)
      return;
   MqlRates bar = r[bars - 1];
   double rng = bar.high - bar.low;
   double body = MathAbs(bar.close - bar.open);
   double lowerWick = MathMin(bar.open, bar.close) - bar.low;
   double upperWick = bar.high - MathMax(bar.open, bar.close);
   bool wideBar = (rng > 0.8 * a);
   double c = bar.close;
   if(wideBar && lowerWick > 2.0 * body &&
      c >= bar.low + 2.0 * rng / 3.0 && cum >= 0)
     {
      double sl = bar.low - 0.2 * a;
      ActOnSignal(si, st, ORDER_TYPE_BUY, sl, c + 2.0 * (c - sl));
      return;
     }
   if(wideBar && upperWick > 2.0 * body &&
      c <= bar.low + rng / 3.0 && cum <= 0)
     {
      double sl = bar.high + 0.2 * a;
      ActOnSignal(si, st, ORDER_TYPE_SELL, sl, c - 2.0 * (sl - c));
      return;
     }
   double d0 = delta[InpOFBars - 1], d1 = delta[InpOFBars - 2];
   double share = MathAbs(cum) / absSum;
   if(d0 >= InpOFImbRatio * MathAbs(d1) && d1 < 0 &&
       cum > 0 && share >= InpOFMinCum)
      ActOnSignal(si, st, ORDER_TYPE_BUY, c - 1.0 * a, c + 2.0 * a);
   else if(-d0 >= InpOFImbRatio * MathAbs(d1) && d1 > 0 &&
           cum < 0 && share >= InpOFMinCum)
      ActOnSignal(si, st, ORDER_TYPE_SELL, c + 1.0 * a, c - 2.0 * a);
  }

//+------------------------------------------------------------------+
//| Straddle: dual stop orders around the 4-bar range each hour       |
//+------------------------------------------------------------------+
void SigStraddle(const MqlRates &r[], double a, int si, int st)
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
   for(int twin = 0; twin < 2; twin++)
      ArmDual(si, st, twin, hour, true, hi + buf, lo - buf, a);
  }

//+------------------------------------------------------------------+
//| London: dual stop orders around the Asian range, once per day     |
//+------------------------------------------------------------------+
void SigLondon(const MqlRates &r[], double a, int si, int st)
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
   for(int twin = 0; twin < 2; twin++)
      ArmDual(si, st, twin, day, haveLevels, buy_stop, sell_stop, a);
  }

//+------------------------------------------------------------------+
//| Trailing SL for all trailing-twin positions (uses cached ATR)     |
//+------------------------------------------------------------------+
void TrailAll()
  {
   for(int si = 0; si < g_symCount; si++)
      for(int st = 0; st < STRAT_COUNT; st++)
        {
         string sym = g_syms[si];
         if(((g_trailWin[si] >> st) & 1) == 0)
            continue; // fixed won the verdict: -T twin keeps its static SL
         int magic = TwinMagic(si, st);
         ulong t = PosOf(sym, magic);
         if(t == 0)
            continue;
         double a = g_atr[si][st];
         if(a <= 0)
            continue;
         double open = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl   = PositionGetDouble(POSITION_SL);
         double tp   = PositionGetDouble(POSITION_TP);
         long   type = PositionGetInteger(POSITION_TYPE);
         double bid = SymbolInfoDouble(sym, SYMBOL_BID);
         double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
         long stops_level = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
         double min_dist = stops_level * SymbolInfoDouble(sym, SYMBOL_POINT);

         trade.SetExpertMagicNumber(magic);
         if(type == POSITION_TYPE_BUY)
           {
            double gain = bid - open;
            if(gain < InpTrailActAtr * a)
               continue;
            double new_sl = bid - InpTrailDistAtr * a;
            if(new_sl > sl + InpTrailStepAtr * a && new_sl < bid - min_dist)
              {
               if(trade.PositionModify(t, new_sl, tp))
                  Print(Label(sym, magic), " trail SL -> ", new_sl);
              }
           }
        else
           {
            double gain = open - ask;
            if(gain < InpTrailActAtr * a)
               continue;
            double new_sl = ask + InpTrailDistAtr * a;
            if((sl == 0 || new_sl < sl - InpTrailStepAtr * a) && new_sl > ask + min_dist)
              {
               if(trade.PositionModify(t, new_sl, tp))
                  Print(Label(sym, magic), " trail SL -> ", new_sl);
              }
           }
        }
  }

//+------------------------------------------------------------------+
//| The engine: one sweep every 5s, all symbols x all strategies      |
//+------------------------------------------------------------------+
void OnTimer()
  {
   TrailAll();
   for(int si = 0; si < g_symCount; si++)
     {
      string sym = g_syms[si];
      for(int st = 0; st < STRAT_COUNT; st++)
        {
         MqlRates r[];
         if(ClosedBarsOf(sym, g_tf[st], 300, r) < 30)
            continue;
         double a = CalcATR(r, 14);
         if(a > 0)
            g_atr[si][st] = a;

         if(g_mode[st] == 0)
           {
            // signal strategy: act once per new closed bar
            if(r[ArraySize(r) - 1].time == g_lastBar[si][st])
               continue;
            g_lastBar[si][st] = r[ArraySize(r) - 1].time;
            if(g_atr[si][st] <= 0)
               continue;
            switch(st)
              {
               case 0: SigBreakout(r, g_atr[si][st], si, st); break;
               case 1: if(InpMeanrevEnabled)
                          SigMeanrev(r, g_atr[si][st], si, st);
                       break; // meanrev suspended on FX by default
               case 2: SigMacross(r, g_atr[si][st], si, st);  break;
               case 4: SigSMC(r, g_atr[si][st], si, st);      break;
               case 6: SigSqueeze(r, g_atr[si][st], si, st);  break;
               case 7: SigProfileMulti(r, g_atr[si][st], si, st);   break;
               case 8: SigOrderflowMulti(r, g_atr[si][st], si, st); break;
              }
           }
        else if(g_mode[st] == 1)
           SigStraddle(r, g_atr[si][st], si, st);  // arms+retries every sweep
        else
           SigLondon(r, g_atr[si][st], si, st);
        }
     }
  }

void OnTick()
  {
   // the engine is timer-driven; ticks of the host chart are irrelevant
  }
//+------------------------------------------------------------------+
