"""
Ensemble Strategy Engine — combina sinais de múltiplas estratégias
e retorna score ponderado para o Groq Council
"""
import numpy as np
import pandas as pd
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Ensemble")

class EnsembleStrategy:
    """
    Estratégias:
    1. Trend Following     (EMA ribbon + MACD)
    2. Mean Reversion      (RSI + Bollinger)
    3. Breakout            (volume + BB width)
    4. Momentum            (Stoch RSI + ATR)
    """

    def __init__(self, adaptive_engine=None):
        self.adaptive = adaptive_engine
        self.weights  = {
            "trend"        : 0.35,
            "mean_reversion": 0.30,
            "breakout"     : 0.20,
            "momentum"     : 0.15,
        }

    def analyze(self, df: pd.DataFrame, sentiment: float = 0.0) -> dict:
        if df.empty or len(df) < 30:
            return self._empty_result()

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 2 else last

        scores = {
            "trend"         : self._trend_score(df, last, prev),
            "mean_reversion": self._mean_reversion_score(df, last, prev),
            "breakout"      : self._breakout_score(df, last, prev),
            "momentum"      : self._momentum_score(df, last, prev),
        }

        # Score ponderado: -10 (sell forte) a +10 (buy forte)
        weighted = sum(
            scores[k] * self.weights[k] for k in scores
        )

        # Ajuste por sentimento de notícias [-1, +1]
        weighted += sentiment * 1.5
        weighted  = max(-10, min(10, weighted))

        # Threshold adaptativo
        threshold = 5
        if self.adaptive:
            ct = self.adaptive.get_param("confidence_threshold", 60)
            threshold = ct / 10  # normaliza para escala -10..+10

        action     = "BUY"  if weighted >= threshold  else \
                     "SELL" if weighted <= -threshold  else \
                     "HOLD"

        indicators = self._extract_indicators(last)
        confidence = self._calc_confidence(weighted, scores, indicators)

        result = {
            "action"      : action,
            "confidence"  : confidence,
            "score"       : round(weighted, 3),
            "total_score" : round(weighted, 3),
            "scores"      : {k: round(v, 3) for k, v in scores.items()},
            "indicators"  : indicators,
            "trend_label" : str(last.get("trend", "unknown")),
        }
        log.debug(
            f"Ensemble: {action} | conf={confidence}% | score={weighted:.2f} | "
            f"T={scores['trend']:.1f} MR={scores['mean_reversion']:.1f} "
            f"B={scores['breakout']:.1f} M={scores['momentum']:.1f}"
        )
        return result

    # ── Estratégia 1: Trend Following ────────────────────────

    def _trend_score(self, df, last, prev) -> float:
        score = 0.0

        # EMA ribbon
        e9, e21, e50 = last.get("ema9"), last.get("ema21"), last.get("ema50")
        if all(v is not None and not np.isnan(v) for v in [e9, e21, e50]):
            if e9 > e21 > e50:
                score += 5.0
            elif e9 < e21 < e50:
                score -= 5.0
            elif e9 > e21:
                score += 2.0
            elif e9 < e21:
                score -= 2.0

        # MACD
        macd = last.get("macd")
        msig = last.get("macd_signal")
        phist= prev.get("macd_hist", 0)
        chist= last.get("macd_hist", 0)

        if all(v is not None and not np.isnan(v) for v in [macd, msig, chist, phist]):
            if macd > msig and chist > phist:   # cruzamento ou aceleração alta
                score += 3.0
            elif macd < msig and chist < phist:
                score -= 3.0
            if macd > 0:
                score += 1.0
            elif macd < 0:
                score -= 1.0

        # Preço vs EMA200
        close = last.get("close")
        e200  = last.get("ema200")
        if close and e200 and not np.isnan(e200):
            score += 1.0 if close > e200 else -1.0

        return max(-10, min(10, score))

    # ── Estratégia 2: Mean Reversion ─────────────────────────

    def _mean_reversion_score(self, df, last, prev) -> float:
        score = 0.0

        rsi = last.get("rsi")
        if rsi and not np.isnan(rsi):
            if self.adaptive:
                oversold  = self.adaptive.get_param("rsi_oversold",   config.RSI_OVERSOLD)
                overbought= self.adaptive.get_param("rsi_overbought",  config.RSI_OVERBOUGHT)
            else:
                oversold  = config.RSI_OVERSOLD
                overbought= config.RSI_OVERBOUGHT

            if rsi < oversold:
                score += 6.0 + (oversold - rsi) * 0.2
            elif rsi > overbought:
                score -= 6.0 + (rsi - overbought) * 0.2
            elif rsi < 45:
                score += 1.5
            elif rsi > 55:
                score -= 1.5

        # Bollinger
        close  = last.get("close")
        bb_u   = last.get("bb_upper")
        bb_l   = last.get("bb_lower")
        bb_mid = last.get("bb_middle")
        if all(v is not None and not np.isnan(v) for v in [close, bb_u, bb_l, bb_mid]):
            bb_range = bb_u - bb_l
            if bb_range > 0:
                pos  = (close - bb_l) / bb_range  # 0=lower 1=upper
                if pos < 0.15:
                    score += 4.0
                elif pos > 0.85:
                    score -= 4.0
                elif pos < 0.35:
                    score += 1.5
                elif pos > 0.65:
                    score -= 1.5

        return max(-10, min(10, score))

    # ── Estratégia 3: Breakout ───────────────────────────────

    def _breakout_score(self, df, last, prev) -> float:
        score = 0.0

        # Volume spike
        vol_ratio = last.get("vol_ratio")
        if vol_ratio and not np.isnan(vol_ratio):
            if vol_ratio > 2.5:
                score += 3.0
            elif vol_ratio > 1.5:
                score += 1.5
            elif vol_ratio < 0.5:
                score -= 1.0

        # BB width (squeeze → expansão)
        bb_width = last.get("bb_width")
        prev_bbw = prev.get("bb_width")
        if all(v is not None and not np.isnan(v) for v in [bb_width, prev_bbw]):
            if bb_width > prev_bbw * 1.2:
                close   = last.get("close")
                bb_mid  = last.get("bb_middle")
                if close and bb_mid:
                    score += 3.0 if close > bb_mid else -3.0

        # Rompimento de máxima/mínima recente
        close = last.get("close")
        if close and len(df) >= 20:
            high20 = df["high"].tail(20).max()
            low20  = df["low"].tail(20).min()
            if close >= high20 * 0.998:
                score += 4.0
            elif close <= low20 * 1.002:
                score -= 4.0

        return max(-10, min(10, score))

    # ── Estratégia 4: Momentum ───────────────────────────────

    def _momentum_score(self, df, last, prev) -> float:
        score = 0.0

        # Stochastic RSI
        srsi = last.get("stoch_rsi")
        if srsi is not None and not np.isnan(srsi):
            if srsi < 0.2:
                score += 4.0
            elif srsi > 0.8:
                score -= 4.0
            elif srsi < 0.35:
                score += 1.5
            elif srsi > 0.65:
                score -= 1.5

        # ATR relativo (volatilidade)
        atr   = last.get("atr")
        close = last.get("close")
        if atr and close and close > 0:
            atr_pct = atr / close
            if atr_pct > 0.02:    # > 2% ATR = momentum forte
                score += 2.0
            elif atr_pct < 0.005: # < 0.5% = mercado parado
                score -= 1.0

        # Price rate of change (ROC 5)
        if len(df) >= 5:
            close5 = df["close"].iloc[-5]
            roc    = (last["close"] - close5) / close5 if close5 > 0 else 0
            score += max(-3, min(3, roc * 100))  # cap ±3

        return max(-10, min(10, score))

    def _calc_confidence(self, total_score: float, scores: dict,
                         indicators: dict) -> int:
        """
        Confiança baseada em:
        - Magnitude do score total
        - Concordância entre estratégias (quantas apontam na mesma direção)
        - RSI extremo (oversold/overbought)
        - Volatilidade (ATR / BB_width)
        """
        if total_score == 0:
            return 0

        direction = 1 if total_score > 0 else -1

        # 1. Base: magnitude do score (0-50 pts)
        base = min(50, abs(total_score) * 5)

        # 2. Concordância das estratégias (+0 a +30 pts)
        agreeing = sum(1 for v in scores.values()
                       if v != 0 and (1 if v > 0 else -1) == direction)
        total_strats = max(1, len([v for v in scores.values() if v != 0]))
        agreement_bonus = int((agreeing / total_strats) * 30)

        # 3. RSI extremo (+0 a +15 pts)
        rsi = indicators.get("rsi") or 50
        try:
            rsi = float(rsi)
            if direction > 0 and rsi < 35:
                rsi_bonus = int((35 - rsi) / 35 * 15)
            elif direction < 0 and rsi > 65:
                rsi_bonus = int((rsi - 65) / 35 * 15)
            else:
                rsi_bonus = 0
        except (ValueError, TypeError):
            rsi_bonus = 0

        # 4. Penalidade por baixa volatilidade (+0 ou -5)
        bb_w = indicators.get("bb_width") or 0
        try:
            bb_w = float(bb_w)
            vol_penalty = -5 if bb_w < 0.01 else 0
        except (ValueError, TypeError):
            vol_penalty = 0

        confidence = int(base + agreement_bonus + rsi_bonus + vol_penalty)
        return max(0, min(100, confidence))

    # ── Helpers ───────────────────────────────────────────────

    def _extract_indicators(self, last) -> dict:
        # Campos numéricos
        numeric_keys = [
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_lower", "bb_middle", "bb_width",
            "ema9", "ema21", "ema50", "ema200",
            "atr", "vwap", "vol_ratio", "stoch_rsi"
        ]
        # Campos string (não converter para float)
        string_keys = ["trend"]

        result = {}

        for k in numeric_keys:
            if k in last and last[k] is not None:
                try:
                    v = float(last[k])
                    result[k] = None if (v != v) else round(v, 4)  # NaN check
                except (ValueError, TypeError):
                    result[k] = None
            else:
                result[k] = None

        for k in string_keys:
            result[k] = str(last[k]) if (k in last and last[k] is not None) else None

        return result

    def _empty_result(self) -> dict:
        return {
            "action"     : "HOLD",
            "confidence" : 0,
            "score"      : 0.0,
            "scores"     : {},
            "indicators" : {},
            "trend_label": "unknown"
        }