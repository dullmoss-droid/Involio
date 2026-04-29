import logging
from typing import Optional

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


def _safe_float(value) -> Optional[float]:
    try:
        f = float(value)
        return None if pd.isna(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


class TechnicalAnalyzer:
    """
    Computes a comprehensive set of technical indicators for a given OHLCV DataFrame.
    Returns a flat dict suitable for serialization and passing to the AI decision engine.
    """

    def compute(self, df: pd.DataFrame) -> dict:
        if len(df) < 50:
            logger.warning("Not enough candles (%d) to compute indicators reliably", len(df))

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        result: dict = {}

        # ── Price context ──────────────────────────────────────────────────────
        result["price"] = _safe_float(close.iloc[-1])
        result["price_change_pct_1"] = _safe_float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
        result["price_change_pct_5"] = _safe_float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) >= 6 else None

        # ── RSI ────────────────────────────────────────────────────────────────
        rsi_14 = ta.rsi(close, length=14)
        rsi_21 = ta.rsi(close, length=21)
        result["rsi_14"] = _safe_float(rsi_14.iloc[-1]) if rsi_14 is not None else None
        result["rsi_21"] = _safe_float(rsi_21.iloc[-1]) if rsi_21 is not None else None

        # RSI interpretation
        rsi = result["rsi_14"]
        if rsi is not None:
            if rsi < 30:
                result["rsi_signal"] = "OVERSOLD"
            elif rsi > 70:
                result["rsi_signal"] = "OVERBOUGHT"
            elif rsi < 45:
                result["rsi_signal"] = "BEARISH"
            elif rsi > 55:
                result["rsi_signal"] = "BULLISH"
            else:
                result["rsi_signal"] = "NEUTRAL"

        # ── MACD ───────────────────────────────────────────────────────────────
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            result["macd"] = _safe_float(macd_df["MACD_12_26_9"].iloc[-1])
            result["macd_signal"] = _safe_float(macd_df["MACDs_12_26_9"].iloc[-1])
            result["macd_hist"] = _safe_float(macd_df["MACDh_12_26_9"].iloc[-1])
            prev_hist = _safe_float(macd_df["MACDh_12_26_9"].iloc[-2])
            curr_hist = result["macd_hist"]
            if curr_hist is not None and prev_hist is not None:
                if curr_hist > 0 and prev_hist <= 0:
                    result["macd_crossover"] = "BULLISH_CROSS"
                elif curr_hist < 0 and prev_hist >= 0:
                    result["macd_crossover"] = "BEARISH_CROSS"
                elif curr_hist > 0:
                    result["macd_crossover"] = "BULLISH"
                else:
                    result["macd_crossover"] = "BEARISH"

        # ── Bollinger Bands ────────────────────────────────────────────────────
        bb = ta.bbands(close, length=20, std=2)
        if bb is not None and not bb.empty:
            result["bb_upper"] = _safe_float(bb["BBU_20_2.0"].iloc[-1])
            result["bb_mid"] = _safe_float(bb["BBM_20_2.0"].iloc[-1])
            result["bb_lower"] = _safe_float(bb["BBL_20_2.0"].iloc[-1])
            result["bb_width"] = _safe_float(bb["BBB_20_2.0"].iloc[-1])
            result["bb_pct"] = _safe_float(bb["BBP_20_2.0"].iloc[-1])
            pct = result["bb_pct"]
            if pct is not None:
                if pct < 0.05:
                    result["bb_signal"] = "NEAR_LOWER_BAND"
                elif pct > 0.95:
                    result["bb_signal"] = "NEAR_UPPER_BAND"
                else:
                    result["bb_signal"] = "MID_RANGE"

        # ── EMAs ───────────────────────────────────────────────────────────────
        for length in (9, 21, 50, 200):
            ema = ta.ema(close, length=length)
            result[f"ema_{length}"] = _safe_float(ema.iloc[-1]) if ema is not None else None

        price = result["price"]
        if price and result.get("ema_200"):
            result["above_ema200"] = price > result["ema_200"]
        if price and result.get("ema_50"):
            result["above_ema50"] = price > result["ema_50"]

        # Golden/death cross (EMA9 vs EMA21)
        ema9 = ta.ema(close, length=9)
        ema21 = ta.ema(close, length=21)
        if ema9 is not None and ema21 is not None and len(ema9) >= 2:
            cross_now = ema9.iloc[-1] > ema21.iloc[-1]
            cross_prev = ema9.iloc[-2] > ema21.iloc[-2]
            if cross_now and not cross_prev:
                result["ema_cross"] = "GOLDEN_CROSS"
            elif not cross_now and cross_prev:
                result["ema_cross"] = "DEATH_CROSS"
            elif cross_now:
                result["ema_cross"] = "BULLISH_ALIGNMENT"
            else:
                result["ema_cross"] = "BEARISH_ALIGNMENT"

        # ── ATR (volatility) ───────────────────────────────────────────────────
        atr = ta.atr(high, low, close, length=14)
        result["atr"] = _safe_float(atr.iloc[-1]) if atr is not None else None
        if result["atr"] and price:
            result["atr_pct"] = round(result["atr"] / price * 100, 3)

        # ── ADX (trend strength) ───────────────────────────────────────────────
        adx_df = ta.adx(high, low, close, length=14)
        if adx_df is not None and not adx_df.empty:
            result["adx"] = _safe_float(adx_df["ADX_14"].iloc[-1])
            result["adx_pos"] = _safe_float(adx_df["DMP_14"].iloc[-1])
            result["adx_neg"] = _safe_float(adx_df["DMN_14"].iloc[-1])
            adx = result["adx"]
            if adx is not None:
                if adx < 20:
                    result["trend_strength"] = "WEAK"
                elif adx < 40:
                    result["trend_strength"] = "MODERATE"
                else:
                    result["trend_strength"] = "STRONG"

        # ── Volume analysis ────────────────────────────────────────────────────
        vol_sma = volume.rolling(20).mean()
        result["volume_current"] = _safe_float(volume.iloc[-1])
        result["volume_avg_20"] = _safe_float(vol_sma.iloc[-1])
        if result["volume_avg_20"] and result["volume_current"]:
            ratio = result["volume_current"] / result["volume_avg_20"]
            result["volume_ratio"] = round(ratio, 2)
            result["volume_signal"] = "HIGH" if ratio > 1.5 else ("LOW" if ratio < 0.7 else "NORMAL")

        # ── Stochastic RSI ─────────────────────────────────────────────────────
        stoch_rsi = ta.stochrsi(close)
        if stoch_rsi is not None and not stoch_rsi.empty:
            result["stoch_rsi_k"] = _safe_float(stoch_rsi["STOCHRSIk_14_14_3_3"].iloc[-1])
            result["stoch_rsi_d"] = _safe_float(stoch_rsi["STOCHRSId_14_14_3_3"].iloc[-1])

        # ── Support / Resistance (simplified pivot-based) ──────────────────────
        support, resistance = self._find_support_resistance(df)
        result["support"] = _safe_float(support)
        result["resistance"] = _safe_float(resistance)
        if support and resistance and price:
            result["pct_to_resistance"] = round((resistance - price) / price * 100, 2)
            result["pct_to_support"] = round((price - support) / price * 100, 2)

        # ── Overall trend ──────────────────────────────────────────────────────
        result["trend"] = self._get_trend(result)

        return result

    def _find_support_resistance(self, df: pd.DataFrame, lookback: int = 50) -> tuple[float, float]:
        """Identify nearest support and resistance using recent swing highs/lows."""
        recent = df.tail(lookback)
        price = float(df["close"].iloc[-1])

        highs = recent["high"].values
        lows = recent["low"].values

        # Find swing highs (local maxima)
        swing_highs = []
        swing_lows = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append(lows[i])

        resistance = min((h for h in swing_highs if h > price), default=float(recent["high"].max()))
        support = max((l for l in swing_lows if l < price), default=float(recent["low"].min()))

        return support, resistance

    def _get_trend(self, indicators: dict) -> str:
        """Derive an overall trend label from a set of computed indicators."""
        bullish_signals = 0
        bearish_signals = 0

        if indicators.get("above_ema200"):
            bullish_signals += 2
        elif indicators.get("above_ema200") is False:
            bearish_signals += 2

        if indicators.get("above_ema50"):
            bullish_signals += 1
        elif indicators.get("above_ema50") is False:
            bearish_signals += 1

        crossover = indicators.get("macd_crossover", "")
        if "BULLISH" in crossover:
            bullish_signals += 1
        elif "BEARISH" in crossover:
            bearish_signals += 1

        ema_cross = indicators.get("ema_cross", "")
        if "BULLISH" in ema_cross or "GOLDEN" in ema_cross:
            bullish_signals += 1
        elif "BEARISH" in ema_cross or "DEATH" in ema_cross:
            bearish_signals += 1

        rsi_sig = indicators.get("rsi_signal", "")
        if rsi_sig in ("BULLISH", "OVERSOLD"):
            bullish_signals += 1
        elif rsi_sig in ("BEARISH", "OVERBOUGHT"):
            bearish_signals += 1

        if bullish_signals > bearish_signals + 1:
            return "BULLISH"
        elif bearish_signals > bullish_signals + 1:
            return "BEARISH"
        return "SIDEWAYS"
