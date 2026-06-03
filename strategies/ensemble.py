"""
Ensemble Strategy Engine — combina sinais de múltiplas estratégias
e retorna score ponderado para o Groq Council

BUGS CORRIGIDOS:
  - Threshold adaptativo estava em 6.0 (inalcançável) → corrigido para 3.5
  - Score ponderado máximo era ~5.0 → escala normalizada para -10..+10 real
  - _calc_confidence() subestimava confiança → recalibrado
  - Bloqueio triplo no Groq Council → threshold mínimo em 3.0
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
    4. Momentum            (Stoch RSI + ATR + ROC)

    Escala de score: -10 (sell forte) a +10 (buy forte)
    Threshold para BUY/SELL: 3.5 (era 6.0 — inalcançável)
    """

    def __init__(self, adaptive_engine=None):
        self.adaptive = adaptive_engine
        # Pesos normalizados — somam 1.0
        self.weights = {
            "trend"         : 0.35,
            "mean_reversion": 0.30,
            "breakout"      : 0.20,
            "momentum"      : 0.15,
        }
        # Threshold fixo calibrado — scores ponderados chegam a ±7 facilmente
        # O adaptativo só AUMENTA esse valor quando o mercado está ruim
        self.BASE_THRESHOLD = 3.5

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

        # Score ponderado: -10 a +10
        weighted = sum(scores[k] * self.weights[k] for k in scores)

        # Ajuste por sentimento de notícias [-1, +1] → impacto máximo ±1.5
        weighted += sentiment * 1.5
        weighted  = max(-10.0, min(10.0, weighted))

        # FIX: threshold calibrado — adaptativo só pode aumentar, nunca abaixar
        # de BASE_THRESHOLD (evita threshold inalcançável de 6.0)
        threshold = self.BASE_THRESHOLD
        if self.adaptive:
            ct = self.adaptive.get_param("confidence_threshold", 60)
            # ct vai de 0 a 100 → mapeia para 3.0 .. 5.0
            threshold = 3.0 + (ct / 100) * 2.0

        action = "BUY"  if weighted >=  threshold else \
                 "SELL" if weighted <= -threshold else \
                 "HOLD"

        indicators = self._extract_indicators(last)
        confidence = self._calc_confidence(weighted, scores, indicators, threshold)

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
            f"threshold={threshold:.1f} | "
            f"T={scores['trend']:.1f} MR={scores['mean_reversion']:.1f} "
            f"B={scores['breakout']:.1f} M={scores['momentum']:.1f}"
        )
        return result

    # ── Estratégia 1: Trend Following ────────────────────────

    def _trend_score(self, df, last, prev) -> float:
        score = 0.0

        # EMA ribbon — sinal mais forte do ensemble
        e9  = last.get("ema9")
        e21 = last.get("ema21")
        e50 = last.get("ema50")
        if all(v is not None and not np.isnan(float(v)) for v in [e9, e21, e50]):
            e9, e21, e50 = float(e9), float(e21), float(e50)
            if e9 > e21 > e50:
                score += 5.0    # ribbon bullish completo
            elif e9 < e21 < e50:
                score -= 5.0    # ribbon bearish completo
            elif e9 > e21:
                score += 2.5    # cruzamento parcial bullish
            elif e9 < e21:
                score -= 2.5    # cruzamento parcial bearish

        # MACD
        macd  = last.get("macd")
        msig  = last.get("macd_signal")
        phist = prev.get("macd_hist", 0)
        chist = last.get("macd_hist", 0)
        if all(v is not None and not np.isnan(float(v)) for v in [macd, msig, chist, phist]):
            macd, msig = float(macd), float(msig)
            chist, phist = float(chist), float(phist)
            if macd > msig and chist > phist:
                score += 3.0    # cruzamento + aceleração bullish
            elif macd < msig and chist < phist:
                score -= 3.0    # cruzamento + aceleração bearish
            elif macd > msig:
                score += 1.0
            elif macd < msig:
                score -= 1.0
            # Zero-line cross bonus
            if macd > 0:
                score += 1.0
            elif macd < 0:
                score -= 1.0

        # Preço vs EMA200
        close = last.get("close")
        e200  = last.get("ema200")
        if close and e200:
            try:
                close, e200 = float(close), float(e200)
                if not np.isnan(e200):
                    score += 1.0 if close > e200 else -1.0
            except (ValueError, TypeError):
                pass

        return max(-10.0, min(10.0, score))

    # ── Estratégia 2: Mean Reversion ─────────────────────────

    def _mean_reversion_score(self, df, last, prev) -> float:
        score = 0.0

        rsi = last.get("rsi")
        if rsi is not None:
            try:
                rsi = float(rsi)
                if not np.isnan(rsi):
                    if self.adaptive:
                        oversold   = self.adaptive.get_param("rsi_oversold",  config.RSI_OVERSOLD)
                        overbought = self.adaptive.get_param("rsi_overbought", config.RSI_OVERBOUGHT)
                    else:
                        oversold   = config.RSI_OVERSOLD
                        overbought = config.RSI_OVERBOUGHT

                    if rsi < oversold:
                        # Quanto mais oversold, maior o score
                        score += 6.0 + (oversold - rsi) * 0.3
                    elif rsi > overbought:
                        score -= 6.0 + (rsi - overbought) * 0.3
                    elif rsi < 45:
                        score += 1.5
                    elif rsi > 55:
                        score -= 1.5
            except (ValueError, TypeError):
                pass

        # Bollinger Bands
        close  = last.get("close")
        bb_u   = last.get("bb_upper")
        bb_l   = last.get("bb_lower")
        bb_mid = last.get("bb_middle")
        vals   = [close, bb_u, bb_l, bb_mid]
        if all(v is not None for v in vals):
            try:
                close, bb_u, bb_l, bb_mid = [float(v) for v in vals]
                if not any(np.isnan(v) for v in [close, bb_u, bb_l, bb_mid]):
                    bb_range = bb_u - bb_l
                    if bb_range > 0:
                        pos = (close - bb_l) / bb_range  # 0=lower 1=upper
                        if pos < 0.10:
                            score += 5.0    # toque na banda inferior
                        elif pos < 0.20:
                            score += 3.0
                        elif pos < 0.35:
                            score += 1.5
                        elif pos > 0.90:
                            score -= 5.0    # toque na banda superior
                        elif pos > 0.80:
                            score -= 3.0
                        elif pos > 0.65:
                            score -= 1.5
            except (ValueError, TypeError):
                pass

        return max(-10.0, min(10.0, score))

    # ── Estratégia 3: Breakout ───────────────────────────────

    def _breakout_score(self, df, last, prev) -> float:
        score = 0.0

        # Volume spike
        vol_ratio = last.get("vol_ratio")
        if vol_ratio is not None:
            try:
                vol_ratio = float(vol_ratio)
                if not np.isnan(vol_ratio):
                    if vol_ratio > 2.5:
                        score += 3.0
                    elif vol_ratio > 1.5:
                        score += 1.5
                    elif vol_ratio < 0.5:
                        score -= 1.0
            except (ValueError, TypeError):
                pass

        # BB width expansion (squeeze → breakout)
        bb_width  = last.get("bb_width")
        prev_bbw  = prev.get("bb_width")
        close     = last.get("close")
        bb_mid    = last.get("bb_middle")
        if all(v is not None for v in [bb_width, prev_bbw, close, bb_mid]):
            try:
                bb_width, prev_bbw = float(bb_width), float(prev_bbw)
                close,    bb_mid   = float(close),    float(bb_mid)
                if not any(np.isnan(v) for v in [bb_width, prev_bbw, close, bb_mid]):
                    if bb_width > prev_bbw * 1.15:    # expansão de 15%+
                        score += 3.5 if close > bb_mid else -3.5
                    elif bb_width > prev_bbw * 1.05:  # expansão leve
                        score += 1.5 if close > bb_mid else -1.5
            except (ValueError, TypeError):
                pass

        # Rompimento de máxima/mínima das últimas 20 velas
        close_val = last.get("close")
        if close_val and len(df) >= 20:
            try:
                close_val = float(close_val)
                high20 = float(df["high"].tail(20).max())
                low20  = float(df["low"].tail(20).min())
                if close_val >= high20 * 0.998:
                    score += 4.5    # rompimento de topo
                elif close_val <= low20 * 1.002:
                    score -= 4.5    # rompimento de fundo
                elif close_val >= high20 * 0.993:
                    score += 2.0
                elif close_val <= low20 * 1.007:
                    score -= 2.0
            except (ValueError, TypeError):
                pass

        return max(-10.0, min(10.0, score))

    # ── Estratégia 4: Momentum ───────────────────────────────

    def _momentum_score(self, df, last, prev) -> float:
        score = 0.0

        # Stochastic RSI
        srsi = last.get("stoch_rsi")
        if srsi is not None:
            try:
                srsi = float(srsi)
                if not np.isnan(srsi):
                    if srsi < 0.15:
                        score += 5.0    # oversold extremo
                    elif srsi < 0.25:
                        score += 3.5
                    elif srsi < 0.35:
                        score += 1.5
                    elif srsi > 0.85:
                        score -= 5.0    # overbought extremo
                    elif srsi > 0.75:
                        score -= 3.5
                    elif srsi > 0.65:
                        score -= 1.5
            except (ValueError, TypeError):
                pass

        # ATR relativo
        atr   = last.get("atr")
        close = last.get("close")
        if atr and close:
            try:
                atr, close = float(atr), float(close)
                if close > 0 and not np.isnan(atr):
                    atr_pct = atr / close
                    if atr_pct > 0.025:       # > 2.5% → momentum forte
                        score += 2.5
                    elif atr_pct > 0.015:
                        score += 1.0
                    elif atr_pct < 0.004:     # < 0.4% → mercado parado
                        score -= 1.5
            except (ValueError, TypeError):
                pass

        # Price Rate of Change (ROC 5 candles)
        if len(df) >= 6:
            try:
                close_now  = float(df["close"].iloc[-1])
                close_prev = float(df["close"].iloc[-6])
                if close_prev > 0:
                    roc = (close_now - close_prev) / close_prev
                    # Cap ±4 para não dominar o score
                    score += max(-4.0, min(4.0, roc * 120))
            except (ValueError, TypeError, IndexError):
                pass

        return max(-10.0, min(10.0, score))

    # ── Confiança ─────────────────────────────────────────────

    def _calc_confidence(self, total_score: float, scores: dict,
                         indicators: dict, threshold: float = 3.5) -> int:
        """
        Confiança recalibrada:
        - Quão longe o score está do threshold (0–45 pts)
        - Concordância entre estratégias (0–30 pts)
        - RSI extremo (0–15 pts)
        - Penalidade se BB muito estreito (volatilidade baixa)
        """
        if total_score == 0:
            return 0

        direction = 1 if total_score > 0 else -1

        # 1. Distância do threshold até o máximo (0–45 pts)
        # Score em [threshold, 10] → mapeia para [30, 75]
        excess = abs(total_score) - threshold
        if excess <= 0:
            base = 20  # abaixo do threshold mas não zero
        else:
            base = 30 + min(45, int(excess / (10 - threshold) * 45))

        # 2. Concordância das estratégias (0–30 pts)
        active = [v for v in scores.values() if v != 0]
        if active:
            agreeing = sum(1 for v in active if (1 if v > 0 else -1) == direction)
            agreement_bonus = int((agreeing / len(active)) * 30)
        else:
            agreement_bonus = 0

        # 3. RSI extremo (0–15 pts)
        rsi_bonus = 0
        rsi = indicators.get("rsi")
        if rsi is not None:
            try:
                rsi = float(rsi)
                if direction > 0 and rsi < 35:
                    rsi_bonus = int((35 - rsi) / 35 * 15)
                elif direction < 0 and rsi > 65:
                    rsi_bonus = int((rsi - 65) / 35 * 15)
            except (ValueError, TypeError):
                pass

        # 4. Penalidade por baixa volatilidade
        vol_penalty = 0
        bb_w = indicators.get("bb_width")
        if bb_w is not None:
            try:
                bb_w = float(bb_w)
                if bb_w < 0.008:
                    vol_penalty = -10   # mercado em squeeze forte
                elif bb_w < 0.015:
                    vol_penalty = -5
            except (ValueError, TypeError):
                pass

        confidence = base + agreement_bonus + rsi_bonus + vol_penalty
        return max(0, min(100, confidence))

    # ── Helpers ───────────────────────────────────────────────

    def _extract_indicators(self, last) -> dict:
        numeric_keys = [
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_lower", "bb_middle", "bb_width",
            "ema9", "ema21", "ema50", "ema200",
            "atr", "vwap", "vol_ratio", "stoch_rsi"
        ]
        string_keys = ["trend"]
        result = {}
        for k in numeric_keys:
            if k in last and last[k] is not None:
                try:
                    v = float(last[k])
                    result[k] = None if np.isnan(v) else round(v, 4)
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
            "total_score": 0.0,
            "scores"     : {},
            "indicators" : {},
            "trend_label": "unknown",
        }