//+------------------------------------------------------------------+
//| XAUUSD Smart Money + Volume Profile Scalper                      |
//| Supply/Demand + POC + M5 trend + M1 confirmation                 |
//| Educational starting point. Backtest and demo-test before use.   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "M1 supply/demand + tick-volume POC EA with hard SL, TP, break-even and trailing stop."

#include <Trade/Trade.mqh>
CTrade trade;

//--------------------------- Inputs ---------------------------------
input group "General"
input ulong  InpMagicNumber            = 26092501;
input ENUM_TIMEFRAMES InpEntryTF       = PERIOD_M1;
input ENUM_TIMEFRAMES InpTrendTF       = PERIOD_M5;
input bool   InpAllowBuy               = true;
input bool   InpAllowSell              = true;
input bool   InpOnePositionOnly        = true;
input int    InpMaxTradesPerDay        = 30;
input int    InpSlippagePoints         = 30;

input group "Trend and Structure"
input int    InpFastEMA                = 20;
input int    InpSlowEMA                = 50;
input int    InpSwingLookback          = 35;
input int    InpImpulseATRPeriod       = 14;
input double InpImpulseATRMultiplier  = 1.20;
input int    InpZoneMaxAgeBars         = 80;
input double InpZoneBufferATR          = 0.15;

input group "Volume Profile / POC"
input int    InpProfileLookbackBars    = 120;
input int    InpProfileBins            = 48;
input double InpPOCMaxDistanceATR      = 0.60;
input bool   InpRequirePOCConfluence   = true;

input group "Entry Confirmation"
input double InpMinBodyToRange         = 0.35;
input double InpMinWickToRange         = 0.20;
input double InpEntryZoneToleranceATR  = 0.20;
input bool   InpRequireTrendFilter     = true;

input group "Risk and Initial SL/TP"
input bool   InpUseRiskPercent         = true;
input double InpRiskPercent            = 0.50;
input double InpFixedLot               = 0.01;
input double InpSL_ATR_Multiplier      = 1.50;
input double InpTP_RiskReward          = 1.50;
input int    InpMinSLPoints            = 250;
input int    InpMaxSLPoints            = 2500;
input double InpMaxLot                 = 2.00;

input group "Break-even and Trailing Stop"
input bool   InpUseBreakEven           = true;
input double InpBreakEvenTriggerR      = 0.80;
input int    InpBreakEvenOffsetPoints  = 20;
input bool   InpUseTrailingStop        = true;
input double InpTrailStartR            = 1.00;
input double InpTrailATRMultiplier     = 1.00;
input int    InpTrailMinStepPoints     = 25;
input bool   InpUseChandelierTrail     = true;
input int    InpChandelierLookback     = 12;

input group "Execution Filters"
input int    InpMaxSpreadPoints        = 100;
input bool   InpUseTradingHours        = false;
input int    InpStartHour              = 7;   // broker server time
input int    InpEndHour                = 22;  // broker server time
input bool   InpAvoidFridayLate        = true;
input int    InpFridayCutoffHour       = 20;

//--------------------------- Globals --------------------------------
int hFastEMA = INVALID_HANDLE;
int hSlowEMA = INVALID_HANDLE;
int hATR     = INVALID_HANDLE;
datetime lastBarTime = 0;
int tradesToday = 0;
int dayOfYear = -1;

//+------------------------------------------------------------------+
//| Utility functions                                                |
//+------------------------------------------------------------------+
double PointValue()
{
   return SymbolInfoDouble(_Symbol, SYMBOL_POINT);
}

int DigitsValue()
{
   return (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
}

double NormalizePrice(double price)
{
   return NormalizeDouble(price, DigitsValue());
}

bool IsNewBar()
{
   datetime t = iTime(_Symbol, InpEntryTF, 0);
   if(t == 0) return false;
   if(t != lastBarTime)
   {
      lastBarTime = t;
      return true;
   }
   return false;
}

void RefreshDailyCounter()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != dayOfYear)
   {
      dayOfYear = dt.day_of_year;
      tradesToday = 0;
   }
}

bool TradingHoursOK()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(InpAvoidFridayLate && dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour)
      return false;

   if(!InpUseTradingHours) return true;

   if(InpStartHour <= InpEndHour)
      return (dt.hour >= InpStartHour && dt.hour < InpEndHour);

   // Overnight session, e.g. 22 to 6
   return (dt.hour >= InpStartHour || dt.hour < InpEndHour);
}

double CurrentSpreadPoints()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return 999999;
   return (tick.ask - tick.bid) / PointValue();
}

bool GetBufferValue(int handle, int buffer, int shift, double &value)
{
   double arr[];
   ArraySetAsSeries(arr, true);
   if(CopyBuffer(handle, buffer, shift, 1, arr) != 1) return false;
   value = arr[0];
   return true;
}

double GetATR(ENUM_TIMEFRAMES tf, int period, int shift=1)
{
   int handle = iATR(_Symbol, tf, period);
   if(handle == INVALID_HANDLE) return 0;
   double val[];
   ArraySetAsSeries(val, true);
   double result = 0;
   if(CopyBuffer(handle, 0, shift, 1, val) == 1) result = val[0];
   IndicatorRelease(handle);
   return result;
}

bool GetRates(ENUM_TIMEFRAMES tf, int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, tf, 0, count, rates);
   return copied >= count;
}

bool HasOurPosition()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         return true;
   }
   return false;
}

double NormalizeVolume(double lots)
{
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   lots = MathMax(minLot, MathMin(lots, MathMin(maxLot, InpMaxLot)));
   if(step > 0) lots = MathFloor(lots / step) * step;

   int volDigits = 2;
   if(step >= 1.0) volDigits = 0;
   else if(step >= 0.1) volDigits = 1;
   else if(step >= 0.01) volDigits = 2;
   else volDigits = 3;

   return NormalizeDouble(lots, volDigits);
}

double CalculateLots(double slDistancePrice)
{
   if(!InpUseRiskPercent) return NormalizeVolume(InpFixedLot);

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * InpRiskPercent / 100.0;
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

   if(tickSize <= 0 || tickValue <= 0 || slDistancePrice <= 0)
      return NormalizeVolume(InpFixedLot);

   double lossPerLot = (slDistancePrice / tickSize) * tickValue;
   if(lossPerLot <= 0) return NormalizeVolume(InpFixedLot);

   return NormalizeVolume(riskMoney / lossPerLot);
}

bool TrendBullish()
{
   double fast, slow;
   if(!GetBufferValue(hFastEMA, 0, 1, fast) ||
      !GetBufferValue(hSlowEMA, 0, 1, slow)) return false;

   MqlRates r[];
   if(!GetRates(InpTrendTF, 3, r)) return false;

   return (fast > slow && r[1].close > fast);
}

bool TrendBearish()
{
   double fast, slow;
   if(!GetBufferValue(hFastEMA, 0, 1, fast) ||
      !GetBufferValue(hSlowEMA, 0, 1, slow)) return false;

   MqlRates r[];
   if(!GetRates(InpTrendTF, 3, r)) return false;

   return (fast < slow && r[1].close < fast);
}

// Detect the most recent confirmed local swing low/high.
bool FindRecentSwingLow(double &swingPrice, int &swingShift)
{
   MqlRates r[];
   int need = InpSwingLookback + 10;
   if(!GetRates(InpEntryTF, need, r)) return false;

   for(int i=3; i<InpSwingLookback; i++)
   {
      if(r[i].low < r[i-1].low && r[i].low < r[i-2].low &&
         r[i].low <= r[i+1].low && r[i].low <= r[i+2].low)
      {
         swingPrice = r[i].low;
         swingShift = i;
         return true;
      }
   }
   return false;
}

bool FindRecentSwingHigh(double &swingPrice, int &swingShift)
{
   MqlRates r[];
   int need = InpSwingLookback + 10;
   if(!GetRates(InpEntryTF, need, r)) return false;

   for(int i=3; i<InpSwingLookback; i++)
   {
      if(r[i].high > r[i-1].high && r[i].high > r[i-2].high &&
         r[i].high >= r[i+1].high && r[i].high >= r[i+2].high)
      {
         swingPrice = r[i].high;
         swingShift = i;
         return true;
      }
   }
   return false;
}

// Supply/demand zone proxy:
// Find recent opposite-color candle followed by a sufficiently large impulse.
// Demand zone uses the base candle's low-to-body top; supply uses body bottom-to-high.
bool FindDemandZone(double &zoneLow, double &zoneHigh)
{
   MqlRates r[];
   int need = MathMax(InpZoneMaxAgeBars + 5, 30);
   if(!GetRates(InpEntryTF, need, r)) return false;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return false;

   for(int i=2; i<InpZoneMaxAgeBars; i++)
   {
      // Candidate bearish/base candle followed by bullish impulse at more recent index.
      if(r[i].close >= r[i].open) continue;

      bool impulseFound = false;
      for(int j=i-1; j>=MathMax(1, i-3); j--)
      {
         if(r[j].close > r[j].open &&
            (r[j].close - r[j].open) >= atr * InpImpulseATRMultiplier &&
            r[j].close > r[i].high)
         {
            impulseFound = true;
            break;
         }
      }

      if(impulseFound)
      {
         zoneLow = r[i].low;
         zoneHigh = MathMax(r[i].open, r[i].close);
         return true;
      }
   }
   return false;
}

bool FindSupplyZone(double &zoneLow, double &zoneHigh)
{
   MqlRates r[];
   int need = MathMax(InpZoneMaxAgeBars + 5, 30);
   if(!GetRates(InpEntryTF, need, r)) return false;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return false;

   for(int i=2; i<InpZoneMaxAgeBars; i++)
   {
      // Candidate bullish/base candle followed by bearish impulse at more recent index.
      if(r[i].close <= r[i].open) continue;

      bool impulseFound = false;
      for(int j=i-1; j>=MathMax(1, i-3); j--)
      {
         if(r[j].close < r[j].open &&
            (r[j].open - r[j].close) >= atr * InpImpulseATRMultiplier &&
            r[j].close < r[i].low)
         {
            impulseFound = true;
            break;
         }
      }

      if(impulseFound)
      {
         zoneLow = MathMin(r[i].open, r[i].close);
         zoneHigh = r[i].high;
         return true;
      }
   }
   return false;
}

// Approximate tick-volume profile: each bar's tick volume is assigned
// to its typical price (H+L+C)/3 bin. POC is the bin with greatest volume.
bool CalculatePOC(double &poc)
{
   int count = MathMax(InpProfileLookbackBars, 20);
   MqlRates r[];
   if(!GetRates(InpEntryTF, count+1, r)) return false;

   double low = r[1].low;
   double high = r[1].high;
   for(int i=1; i<=count; i++)
   {
      low = MathMin(low, r[i].low);
      high = MathMax(high, r[i].high);
   }
   if(high <= low) return false;

   int bins = MathMax(InpProfileBins, 10);
   double volumeBins[];
   ArrayResize(volumeBins, bins);
   ArrayInitialize(volumeBins, 0.0);

   double binSize = (high-low)/bins;
   for(int i=1; i<=count; i++)
   {
      double typical = (r[i].high + r[i].low + r[i].close)/3.0;
      int index = (int)MathFloor((typical-low)/binSize);
      index = MathMax(0, MathMin(index, bins-1));
      volumeBins[index] += (double)r[i].tick_volume;
   }

   int pocIndex = 0;
   double maxVol = volumeBins[0];
   for(int b=1; b<bins; b++)
   {
      if(volumeBins[b] > maxVol)
      {
         maxVol = volumeBins[b];
         pocIndex = b;
      }
   }

   poc = low + (pocIndex + 0.5)*binSize;
   return true;
}

bool BullishConfirmation()
{
   MqlRates r[];
   if(!GetRates(InpEntryTF, 4, r)) return false;

   MqlRates c = r[1]; // last closed candle
   MqlRates p = r[2];
   double range = c.high-c.low;
   if(range <= 0) return false;

   double body = MathAbs(c.close-c.open);
   double lowerWick = MathMin(c.open,c.close)-c.low;
   bool bullishBody = c.close > c.open && body/range >= InpMinBodyToRange;
   bool bullishEngulf = c.close > c.open && p.close < p.open &&
                        c.close >= p.open && c.open <= p.close;
   bool rejection = c.close > c.open && lowerWick/range >= InpMinWickToRange &&
                    c.close > (c.low + range*0.60);

   return bullishBody || bullishEngulf || rejection;
}

bool BearishConfirmation()
{
   MqlRates r[];
   if(!GetRates(InpEntryTF, 4, r)) return false;

   MqlRates c = r[1];
   MqlRates p = r[2];
   double range = c.high-c.low;
   if(range <= 0) return false;

   double body = MathAbs(c.close-c.open);
   double upperWick = c.high-MathMax(c.open,c.close);
   bool bearishBody = c.close < c.open && body/range >= InpMinBodyToRange;
   bool bearishEngulf = c.close < c.open && p.close > p.open &&
                        c.close <= p.open && c.open >= p.close;
   bool rejection = c.close < c.open && upperWick/range >= InpMinWickToRange &&
                    c.close < (c.low + range*0.40);

   return bearishBody || bearishEngulf || rejection;
}

bool PriceNearZone(double price, double zoneLow, double zoneHigh, double tolerance)
{
   return (price >= zoneLow-tolerance && price <= zoneHigh+tolerance);
}

bool POCConfluenceOK(double price, double poc, double atr)
{
   if(!InpRequirePOCConfluence) return true;
   if(atr <= 0) return false;
   return MathAbs(price-poc) <= atr*InpPOCMaxDistanceATR;
}

double GetRecentLowest(int lookback)
{
   MqlRates r[];
   if(!GetRates(InpEntryTF, lookback+2, r)) return 0;
   double lowest = r[1].low;
   for(int i=1; i<=lookback; i++) lowest = MathMin(lowest, r[i].low);
   return lowest;
}

double GetRecentHighest(int lookback)
{
   MqlRates r[];
   if(!GetRates(InpEntryTF, lookback+2, r)) return 0;
   double highest = r[1].high;
   for(int i=1; i<=lookback; i++) highest = MathMax(highest, r[i].high);
   return highest;
}

// Respect broker stop/freeze levels and normalize SL/TP.
void AdjustStopsForBroker(bool isBuy, double entry, double &sl, double &tp)
{
   double point = PointValue();
   int stopLevel = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minDist = MathMax(stopLevel*point, 2*point);

   if(isBuy)
   {
      if(entry-sl < minDist) sl = entry-minDist;
      if(tp-entry < minDist) tp = entry+minDist;
   }
   else
   {
      if(sl-entry < minDist) sl = entry+minDist;
      if(entry-tp < minDist) tp = entry-minDist;
   }

   sl = NormalizePrice(sl);
   tp = NormalizePrice(tp);
}

bool OpenBuy(double zoneLow)
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return false;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return false;

   double point = PointValue();
   double slDist = MathMax(atr*InpSL_ATR_Multiplier, InpMinSLPoints*point);
   slDist = MathMin(slDist, InpMaxSLPoints*point);

   // Place SL beneath the zone if that gives a sensible stop; otherwise ATR stop.
   double sl = MathMin(tick.ask-slDist, zoneLow-atr*InpZoneBufferATR);
   double actualDist = tick.ask-sl;
   if(actualDist > InpMaxSLPoints*point)
   {
      sl = tick.ask-InpMaxSLPoints*point;
      actualDist = tick.ask-sl;
   }

   double tp = tick.ask + actualDist*InpTP_RiskReward;
   AdjustStopsForBroker(true, tick.ask, sl, tp);

   double lots = CalculateLots(tick.ask-sl);
   if(lots <= 0) return false;

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   bool ok = trade.Buy(lots, _Symbol, 0.0, sl, tp, "SMVP Buy");
   if(ok) tradesToday++;
   else Print("Buy failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   return ok;
}

bool OpenSell(double zoneHigh)
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return false;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return false;

   double point = PointValue();
   double slDist = MathMax(atr*InpSL_ATR_Multiplier, InpMinSLPoints*point);
   slDist = MathMin(slDist, InpMaxSLPoints*point);

   double sl = MathMax(tick.bid+slDist, zoneHigh+atr*InpZoneBufferATR);
   double actualDist = sl-tick.bid;
   if(actualDist > InpMaxSLPoints*point)
   {
      sl = tick.bid+InpMaxSLPoints*point;
      actualDist = sl-tick.bid;
   }

   double tp = tick.bid - actualDist*InpTP_RiskReward;
   AdjustStopsForBroker(false, tick.bid, sl, tp);

   double lots = CalculateLots(sl-tick.bid);
   if(lots <= 0) return false;

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   bool ok = trade.Sell(lots, _Symbol, 0.0, sl, tp, "SMVP Sell");
   if(ok) tradesToday++;
   else Print("Sell failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   return ok;
}

// Store initial risk distance in position comment is not reliable across brokers.
// Use current SL distance from open as a conservative R estimate; once SL advances,
// preserve an approximate initial R using Global Variables keyed by position identifier.
string RiskGVName(ulong positionId)
{
   return "SMVP_R_" + IntegerToString((long)positionId);
}

void ManageOpenPositions()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return;

   double point = PointValue();
   int stopLevel = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int freezeLevel = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minStopDist = MathMax(stopLevel, freezeLevel)*point;
   // hardening: after a failed modify, back off 30 s so a latency/timeout window
   // cannot turn into a per-tick retry storm.
   static datetime s_lastModFail = 0;
   if(s_lastModFail > 0 && TimeCurrent() - s_lastModFail < 30) return;

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL = PositionGetDouble(POSITION_SL);
      double currentTP = PositionGetDouble(POSITION_TP);
      ulong posId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);

      string gv = RiskGVName(posId);
      double initialRisk = 0;
      if(GlobalVariableCheck(gv))
         initialRisk = GlobalVariableGet(gv);
      else
      {
         if(currentSL > 0) initialRisk = MathAbs(openPrice-currentSL);
         if(initialRisk <= 0) initialRisk = atr*InpSL_ATR_Multiplier;
         GlobalVariableSet(gv, initialRisk);
      }
      if(initialRisk <= 0) continue;

      double marketPrice = (type == POSITION_TYPE_BUY) ? tick.bid : tick.ask;
      double profitDistance = (type == POSITION_TYPE_BUY) ?
                              marketPrice-openPrice : openPrice-marketPrice;
      double profitR = profitDistance/initialRisk;

      double newSL = currentSL;
      bool modify = false;

      // Break-even moves SL to entry plus/minus a small offset.
      if(InpUseBreakEven && profitR >= InpBreakEvenTriggerR)
      {
         double beSL = (type == POSITION_TYPE_BUY) ?
                       openPrice + InpBreakEvenOffsetPoints*point :
                       openPrice - InpBreakEvenOffsetPoints*point;

         if(type == POSITION_TYPE_BUY && (currentSL == 0 || beSL > newSL))
         {
            newSL = beSL;
            modify = true;
         }
         if(type == POSITION_TYPE_SELL && (currentSL == 0 || beSL < newSL))
         {
            newSL = beSL;
            modify = true;
         }
      }

      // ATR trailing stop. Optional chandelier uses recent high/low extremes.
      if(InpUseTrailingStop && profitR >= InpTrailStartR)
      {
         double trailDistance = atr*InpTrailATRMultiplier;
         double trailSL = 0;

         if(type == POSITION_TYPE_BUY)
         {
            trailSL = tick.bid-trailDistance;
            if(InpUseChandelierTrail)
            {
               double highest = GetRecentHighest(InpChandelierLookback);
               if(highest > 0) trailSL = MathMax(trailSL, highest-trailDistance);
            }

            if((currentSL == 0 || trailSL > newSL) &&
               (currentSL == 0 || trailSL-newSL >= InpTrailMinStepPoints*point))
            {
               newSL = trailSL;
               modify = true;
            }
         }
         else
         {
            trailSL = tick.ask+trailDistance;
            if(InpUseChandelierTrail)
            {
               double lowest = GetRecentLowest(InpChandelierLookback);
               if(lowest > 0) trailSL = MathMin(trailSL, lowest+trailDistance);
            }

            if((currentSL == 0 || trailSL < newSL) &&
               (currentSL == 0 || newSL-trailSL >= InpTrailMinStepPoints*point))
            {
               newSL = trailSL;
               modify = true;
            }
         }
      }

      if(!modify) continue;

      // Keep the stop on the valid side of current market and outside broker stop level.
      if(type == POSITION_TYPE_BUY)
      {
         double maxAllowedSL = tick.bid-minStopDist;
         newSL = MathMin(newSL, maxAllowedSL);
         newSL = NormalizePrice(newSL);
         if(newSL <= 0 || (currentSL > 0 && newSL <= currentSL)) continue;
      }
      else
      {
         double minAllowedSL = tick.ask+minStopDist;
         newSL = MathMax(newSL, minAllowedSL);
         newSL = NormalizePrice(newSL);
         if(newSL <= 0 || (currentSL > 0 && newSL >= currentSL)) continue;
      }

      if(!trade.PositionModify(ticket, newSL, currentTP))
      {
         s_lastModFail = TimeCurrent();
         Print("PositionModify failed. Ticket=", ticket,
               " Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription(),
               " -- retry in 30s");
      }
   }
}

void CheckForEntry()
{
   RefreshDailyCounter();
   if(tradesToday >= InpMaxTradesPerDay) return;
   if(!TradingHoursOK()) return;
   if(CurrentSpreadPoints() > InpMaxSpreadPoints) return;
   if(InpOnePositionOnly && HasOurPosition()) return;

   double atr = GetATR(InpEntryTF, InpImpulseATRPeriod, 1);
   if(atr <= 0) return;

   double poc;
   if(!CalculatePOC(poc)) return;

   double demandLow, demandHigh, supplyLow, supplyHigh;
   bool hasDemand = FindDemandZone(demandLow, demandHigh);
   bool hasSupply = FindSupplyZone(supplyLow, supplyHigh);

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;

   double tolerance = atr*InpEntryZoneToleranceATR;
   double mid = (tick.ask+tick.bid)/2.0;

   bool bullTrend = TrendBullish();
   bool bearTrend = TrendBearish();

   // Buy: bullish trend, price retests demand, POC confluence, bullish closed candle.
   if(InpAllowBuy && hasDemand &&
      (!InpRequireTrendFilter || bullTrend) &&
      PriceNearZone(mid, demandLow, demandHigh, tolerance) &&
      POCConfluenceOK(mid, poc, atr) &&
      BullishConfirmation())
   {
      OpenBuy(demandLow);
      return;
   }

   // Sell: bearish trend, price retests supply, POC confluence, bearish closed candle.
   if(InpAllowSell && hasSupply &&
      (!InpRequireTrendFilter || bearTrend) &&
      PriceNearZone(mid, supplyLow, supplyHigh, tolerance) &&
      POCConfluenceOK(mid, poc, atr) &&
      BearishConfirmation())
   {
      OpenSell(supplyHigh);
      return;
   }
}

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpFastEMA <= 0 || InpSlowEMA <= 0 || InpFastEMA >= InpSlowEMA)
   {
      Print("Invalid EMA inputs: fast EMA must be less than slow EMA.");
      return INIT_PARAMETERS_INCORRECT;
   }

   hFastEMA = iMA(_Symbol, InpTrendTF, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   hSlowEMA = iMA(_Symbol, InpTrendTF, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   hATR = iATR(_Symbol, InpEntryTF, InpImpulseATRPeriod);

   if(hFastEMA == INVALID_HANDLE || hSlowEMA == INVALID_HANDLE || hATR == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles.");
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   RefreshDailyCounter();
   lastBarTime = iTime(_Symbol, InpEntryTF, 0);

   Print("SMVP EA initialized on ", _Symbol,
         ". Entry TF=", EnumToString(InpEntryTF),
         ", trend TF=", EnumToString(InpTrendTF));
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hFastEMA != INVALID_HANDLE) IndicatorRelease(hFastEMA);
   if(hSlowEMA != INVALID_HANDLE) IndicatorRelease(hSlowEMA);
   if(hATR != INVALID_HANDLE) IndicatorRelease(hATR);
}

//+------------------------------------------------------------------+
//| Stuck-stop guard: broker lag can leave price THROUGH an SL/TP    |
//| with nothing executing (2026-09-29 server incident). Re-send the |
//| stop levels (pulsed 1 point further from price so the modify is  |
//| a real change) to re-arm the server stop; if still stuck after   |
//| InpStuckGiveupSec, close market. Single-slot per-ticket state.   |
//+------------------------------------------------------------------+
input group "Stuck-stop guard"
input bool   InpStuckGuard      = true;  // Re-trigger stuck SL/TP
input int    InpStuckThreshPts  = 50;    // Min breach beyond stop (points)
input int    InpStuckPersistSec = 30;    // Breach persistence before re-trigger (s)
input int    InpStuckGiveupSec  = 180;   // Persist this long -> market close (s)

void StuckStopGuard()
{
   if(!InpStuckGuard) return;
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(pt <= 0) return;
   double thresh = InpStuckThreshPts * pt;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;

   ulong  ticket = 0;
   double stop = 0, psl = 0, ptp = 0;
   bool   isBuy = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
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
   if(held < InpStuckGiveupSec) return;   // breach not old enough -> wait
   if(s_lastTry > 0 && TimeCurrent() - s_lastTry < 20) return;
   s_lastTry = TimeCurrent();

   // breached stop = wrong side of price: modifying is impossible, closing
   // is the only valid action (2026-09-30 fix, mirrors FTTestCore)
   if(trade.PositionClose(ticket))
   {
      Print("SMVP ", InpMagicNumber, " STUCK-STOP CLOSE #", ticket,
            " after ", held, "s breached (stop=", stop, " sl=", psl,
            " tp=", ptp, ") ret=", trade.ResultRetcode());
      s_ticket = 0; s_since = 0; s_resent = 0; s_lastTry = 0;
   }
   else
      Print("SMVP ", InpMagicNumber, " STUCK-STOP CLOSE #", ticket,
            " FAILED ret=", trade.ResultRetcode(), " (",
            trade.ResultRetcodeDescription(), ") will retry");
}

//+------------------------------------------------------------------+
//| Main tick                                                        |
//+------------------------------------------------------------------+
void OnTick()
{
   // Manage stops on every tick, not only at candle close.
   ManageOpenPositions();
   StuckStopGuard(); // re-trigger SL/TP the broker left unexecuted

   // New entries are evaluated once per newly opened M1 bar, using
   // closed candles to reduce intrabar false signals.
   if(IsNewBar())
      CheckForEntry();
}
//+------------------------------------------------------------------+
