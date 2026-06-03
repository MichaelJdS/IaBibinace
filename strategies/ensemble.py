"""
Ensemble Strategy Engine — versão recalibrada
- score mais utilizável
- confiança acima de 50 quando há consenso real
- confirmação de tendência multi-timeframe
"""
import numpy as np
import pandas as pd
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Ensemble")


class EnsembleStrategy:
    def __init__(self, adaptive_engine=None):
        self.adaptive = adaptive_engine
        self.weights = {
            "trend": 0.34,
            "mean_reversion": 0.22,
            "breakout": 0.24,
            "momentum": 0.20,
        }

    def analyze(self, df: pd.DataFrame, sentiment: float = 0.0, context: dict | None = None) -> dict:
        if df.empty or len(df) < 50:
            return self._empty_result()

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        context = context or {}

        scores = {
            "trend": self._trend_score(df, last, prev),
            "mean_reversion": self._mean_reversion_score(df, last, prev),
            "breakout": self._breakout_score(df, last, prev),
            "momentum": self._momentum_score(df, last, prev),
        }

        weighted_raw = sum(scores[k] * self.weights[k] for k in scores)
        mtf_bonus = self._multi_tf_bonus(context)
        sentiment_bonus = float(sentiment) * 1.2

        weighted = weighted_raw + mtf_bonus + sentiment_bonus
        weighted = max(-10.0, min(10.0, weighted))

        threshold = self._resolve_threshold(context)
        action = "BUY" if weighted >= threshold else "SELL" if weighted <= -threshold else "HOLD"

        indicators = self._extract_indicators(last)
        confidence = self._calc_confidence(weighted, scores, indicators, threshold, context)

        result = {
            "action": action,
            "confidence": confidence,
            "score": round(weighted, 3),
            "total_score": round(weighted, 3),
            "scores": {k: round(v, 3) for k, v in scores.items()},
            "indicators": indicators,
            "trend_label": str(last.get("trend", "unknown")),
            "threshold_used": round(threshold, 3),
            "mtf_bonus": round(mtf_bonus, 3),
        }

        log.debug(
            f"Ensemble {action} score={weighted:.2f} conf={confidence}% "
            f"thr={threshold:.2f} mtf={mtf_bonus:.2f} "
            f"T={scores['trend']:.1f} MR={scores['mean_reversion']:.1f} "
            f"B={scores['breakout']:.1f} M={scores['momentum']:.1f}"
        )
        return result

    def _resolve_threshold(self, context: dict) -> float:
        regime = str(context.get("market_regime", "")).lower()
        base = float(getattr(config, "ENSEMBLE_BASE_THRESHOLD", 2.4))
        if regime in ("trending_up", "trending_down", "trend", "strong_up", "strong_down"):
            return min(base, getattr(config, "TRENDING_THRESHOLD", 2.2))
        if regime in ("ranging", "sideways"):
            return max(base, getattr(config, "RANGING_THRESHOLD", 3.0))
        return base

    def _multi_tf_bonus(self, context: dict) -> float:
        primary = str(context.get("primary_trend", "")).lower()
        confirm = str(context.get("confirm_trend", "")).lower()
        higher = str(context.get("higher_trend", "")).lower()
        trends = [t for t in [primary, confirm, higher] if t]

        bull = sum(1 for t in trends if "up" in t or "bull" in t)
        bear = sum(1 for t in trends if "down" in t or "bear" in t)

        if bull >= 2 and bear == 0:
            return 1.2
        if bear >= 2 and bull == 0:
            return -1.2
        if bull >= 2 and bear >= 1:
            return 0.3
        if bear >= 2 and bull >= 1:
            return -0.3
        return 0.0

    def _trend_score(self, df, last, prev) -> float:
        score = 0.0

        e9, e21, e50 = last.get("ema9"), last.get("ema21"), last.get("ema50")
        if all(v is not None and not np.isnan(float(v)) for v in [e9, e21, e50]):
            e9, e21, e50 = float(e9), float(e21), float(e50)
            if e9 > e21 > e50:
                score += 5.5
            elif e9 < e21 < e50:
                score -= 5.5
            elif e9 > e21:
                score += 2.5
            elif e9 < e21:
                score -= 2.5

        macd = last.get("macd")
        msig = last.get("macd_signal")
        phist = prev.get("macd_hist", 0)
        chist = last.get("macd_hist", 0)
        if all(v is not None and not np.isnan(float(v)) for v in [macd, msig, chist, phist]):
            macd, msig, phist, chist = float(macd), float(msig), float(phist), float(chist)
            if macd > msig and chist > phist:
                score += 2.5
            elif macd < msig and chist < phist:
                score -= 2.5
            elif macd > msig:
                score += 1.0
            elif macd < msig:
                score -= 1.0

        close, e200 = last.get("close"), last.get("ema200")
        if close is not None and e200 is not None:
            close, e200 = float(close), float(e200)
            if close > e200:
                score += 1.2
            else:
                score -= 1.2

        return max(-10.0, min(10.0, score))

    def _mean_reversion_score(self, df, last, prev) -> float:
        score = 0.0
        rsi = last.get("rsi")
        if rsi is not None and not np.isnan(float(rsi)):
            rsi = float(rsi)
            oversold = self.adaptive.get_param("rsi_oversold", config.RSI_OVERSOLD) if self.adaptive else config.RSI_OVERSOLD
            overbought = self.adaptive.get_param("rsi_overbought", config.RSI_OVERBOUGHT) if self.adaptive else config.RSI_OVERBOUGHT

            if rsi < oversold:
                score += 5.5 + (oversold - rsi) * 0.25
            elif rsi > overbought:
                score -= 5.5 + (rsi - overbought) * 0.25
            elif rsi < 43:
                score += 1.5
            elif rsi > 57:
                score -= 1.5

        close = last.get("close")
        bb_u = last.get("bb_upper")
        bb_l = last.get("bb_lower")
        if all(v is not None for v in [close, bb_u, bb_l]):
            close, bb_u, bb_l = float(close), float(bb_u), float(bb_l)
            width = bb_u - bb_l
            if width > 0:
                pos = (close - bb_l) / width
                if pos < 0.10:
                    score += 4.5
                elif pos < 0.20:
                    score += 2.5
                elif pos > 0.90:
                    score -= 4.5
                elif pos > 0.80:
                    score -= 2.5

        return max(-10.0, min(10.0, score))

    def _breakout_score(self, df, last, prev) -> float:
        score = 0.0

        vol_ratio = last.get("vol_ratio")
        if vol_ratio is not None and not np.isnan(float(vol_ratio)):
            vol_ratio = float(vol_ratio)
            if vol_ratio > 2.2:
                score += 3.0
            elif vol_ratio > 1.4:
                score += 1.5
            elif vol_ratio < 0.6:
                score -= 1.0

        bb_width = last.get("bb_width")
        prev_bbw = prev.get("bb_width")
        close = last.get("close")
        bb_mid = last.get("bb_middle")
        if all(v is not None for v in [bb_width, prev_bbw, close, bb_mid]):
            bb_width, prev_bbw, close, bb_mid = map(float, [bb_width, prev_bbw, close, bb_mid])
            if bb_width > prev_bbw * 1.15:
                score += 3.0 if close > bb_mid else -3.0

        if len(df) >= 20 and last.get("close") is not None:
            close = float(last["close"])
            high20 = float(df["high"].tail(20).max())
            low20 = float(df["low"].tail(20).min())
            if close >= high20 * 0.999:
                score += 4.2
            elif close <= low20 * 1.001:
                score -= 4.2

        return max(-10.0, min(10.0, score))

    def _momentum_score(self, df, last, prev) -> float:
        score = 0.0

        srsi = last.get("stoch_rsi")
        if srsi is not None and not np.isnan(float(srsi)):
            srsi = float(srsi)
            if srsi < 0.15:
                score += 4.0
            elif srsi < 0.30:
                score += 2.0
            elif srsi > 0.85:
                score -= 4.0
            elif srsi > 0.70:
                score -= 2.0

        atr = last.get("atr")
        close = last.get("close")
        if atr is not None and close is not None and float(close) > 0:
            atr_pct = float(atr) / float(close)
            if atr_pct > 0.018:
                score += 1.5
            elif atr_pct < 0.004:
                score -= 1.0

        if len(df) >= 6:
            close_now = float(df["close"].iloc[-1])
            close_prev = float(df["close"].iloc[-6])
            if close_prev > 0:
                roc = (close_now - close_prev) / close_prev
                score += max(-4.0, min(4.0, roc * 130))

        return max(-10.0, min(10.0, score))

    def _calc_confidence(self, total_score: float, scores: dict, indicators: dict,
                         threshold: float = 2.4, context: dict | None = None) -> int:
        if total_score == 0:
            return 0

        context = context or {}
        direction = 1 if total_score > 0 else -1

        score_power = min(40, int(abs(total_score) * 6))
        threshold_edge = min(20, max(0, int((abs(total_score) - threshold) * 10)))

        active = [v for v in scores.values() if abs(v) >= 1.0]
        if active:
            agreeing = sum(1 for v in active if (1 if v > 0 else -1) == direction)
            agreement_bonus = int((agreeing / len(active)) * 25)
        else:
            agreement_bonus = 0

        rsi_bonus = 0
        rsi = indicators.get("rsi")
        if rsi is not None:
            rsi = float(rsi)
            if direction > 0 and rsi < 35:
                rsi_bonus = min(10, int((35 - rsi) * 0.5))
            elif direction < 0 and rsi > 65:
                rsi_bonus = min(10, int((rsi - 65) * 0.5))

        mtf_bonus = 0
        mtf = self._multi_tf_bonus(context)
        if mtf != 0:
            mtf_bonus = 10 if (mtf > 0 and direction > 0) or (mtf < 0 and direction < 0) else -5

        bb_penalty = 0
        bb_w = indicators.get("bb_width")
        if bb_w is not None and float(bb_w) < 0.007:
            bb_penalty = -8

        confidence = score_power + threshold_edge + agreement_bonus + rsi_bonus + mtf_bonus + bb_penalty
        return max(0, min(100, confidence))

    def _extract_indicators(self, last) -> dict:
        numeric_keys = [
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_lower", "bb_middle", "bb_width",
            "ema9", "ema21", "ema50", "ema200",
            "atr", "vwap", "vol_ratio", "stoch_rsi", "adx"
        ]
        string_keys = ["trend"]

        result = {}
        for k in numeric_keys:
            if k in last and last[k] is not None:
                try:
                    v = float(last[k])
                    result[k] = None if (v != v) else round(v, 5)
                except (ValueError, TypeError):
                    result[k] = None
            else:
                result[k] = None

        for k in string_keys:
            result[k] = str(last[k]) if (k in last and last[k] is not None) else None
        return result

    def _empty_result(self) -> dict:
        return {
            "action": "HOLD",
            "confidence": 0,
            "score": 0.0,
            "total_score": 0.0,
            "scores": {},
            "indicators": {},
            "trend_label": "unknown",
            "threshold_used": 0.0,
            "mtf_bonus": 0.0,
        }