"""
Estratégia RSI + MACD + Finnhub Aggregate Signal
Sistema de pontuação 0–10. Threshold mínimo de 5 para agir.
"""
import pandas as pd
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Strategy")

class RSIMACDStrategy:

    def _macd_crossover(self, df: pd.DataFrame) -> str:
        if len(df) < 3:
            return "none"
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        if prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]:
            return "bullish_cross"
        if prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
            return "bearish_cross"
        return "none"

    def decide(self, df: pd.DataFrame, finnhub_signal: str) -> dict:
        if df.empty or "rsi" not in df.columns:
            return {"action": "HOLD", "reason": "Dados insuficientes", "confidence": 0.0}

        last       = df.iloc[-1]
        rsi        = last["rsi"]
        macd_cross = self._macd_crossover(df)
        trend      = last.get("trend", "DOWN")
        bb_pos     = (
            "below_lower" if last["close"] < last["bb_lower"] else
            "above_upper" if last["close"] > last["bb_upper"] else
            "inside"
        )

        score_buy  = 0
        score_sell = 0

        if rsi < config.RSI_OVERSOLD:             score_buy += 3  # RSI < 30
        elif rsi < 40:                            score_buy += 2  # RSI < 40 (novo)
        if macd_cross == "bullish_cross":         score_buy += 3
        if finnhub_signal == "buy":               score_buy += 2
        if trend == "UP":                         score_buy += 1
        if bb_pos == "below_lower":               score_buy += 2  # era +1, agora +2

        if rsi > config.RSI_OVERBOUGHT:           score_sell += 3
        if macd_cross == "bearish_cross":         score_sell += 3
        if finnhub_signal == "sell":              score_sell += 2
        if trend == "DOWN":                       score_sell += 1
        if bb_pos == "above_upper":               score_sell += 1

        log.info(
            f"Score → BUY: {score_buy}/10 | SELL: {score_sell}/10 | "
            f"RSI: {rsi:.1f} | MACD: {macd_cross} | "
            f"Finnhub: {finnhub_signal} | Trend: {trend}"
        )

        THRESHOLD = 3

        if score_buy >= THRESHOLD and score_buy > score_sell:
            return {
                "action"    : "BUY",
                "reason"    : f"RSI={rsi:.1f}, MACD={macd_cross}, Finnhub={finnhub_signal}, Trend={trend}",
                "confidence": round(score_buy / 10, 2),
                "price"     : last["close"]
            }

        if score_sell >= THRESHOLD and score_sell > score_buy:
            return {
                "action"    : "SELL",
                "reason"    : f"RSI={rsi:.1f}, MACD={macd_cross}, Finnhub={finnhub_signal}, Trend={trend}",
                "confidence": round(score_sell / 10, 2),
                "price"     : last["close"]
            }

        return {
            "action"    : "HOLD",
            "reason"    : f"Score insuficiente (buy={score_buy}, sell={score_sell})",
            "confidence": 0.0,
            "price"     : last["close"]
        }