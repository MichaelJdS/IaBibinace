"""
Groq Council — versão recalibrada
- menos veto cego
- resposta mais rápida
- mais alinhado com alta frequência
"""
import time
import json
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("GroqCouncil")

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    log.warning("groq SDK não instalado. Fallback ativo.")


class CouncilState:
    def __init__(self):
        self.regime = "ranging"
        self.bias = "neutral"
        self.veto = False
        self.veto_reason = ""
        self.confidence_multiplier = 1.0
        self.threshold_adjustment = 0
        self.explanation = ""
        self.last_updated = ""
        self._lock = threading.Lock()

    def update(self, data: dict):
        with self._lock:
            self.regime = data.get("regime", self.regime)
            self.bias = data.get("bias", self.bias)
            self.veto = data.get("veto", self.veto)
            self.veto_reason = data.get("veto_reason", self.veto_reason)
            self.confidence_multiplier = data.get("confidence_multiplier", self.confidence_multiplier)
            self.threshold_adjustment = data.get("threshold_adjustment", self.threshold_adjustment)
            self.explanation = data.get("explanation", self.explanation)
            self.last_updated = time.strftime("%H:%M:%S")

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "regime": self.regime,
                "bias": self.bias,
                "veto": self.veto,
                "veto_reason": self.veto_reason,
                "confidence_multiplier": self.confidence_multiplier,
                "threshold_adjustment": self.threshold_adjustment,
                "explanation": self.explanation,
                "last_updated": self.last_updated,
            }


class GroqCouncil:
    def __init__(self):
        self.state = CouncilState()
        self._states = {}
        self._clients = {}
        self._key_idx = 0
        self._key_lock = threading.Lock()
        self._running = False
        self._last_call = 0
        self._min_interval = 1.2
        self._last_groq_call = {}
        self._groq_interval = getattr(config, "GROQ_ANALYSIS_INTERVAL", 15)

        if GROQ_AVAILABLE and config.GROQ_API_KEYS:
            for i, key in enumerate(config.GROQ_API_KEYS):
                self._clients[i] = Groq(api_key=key)
            log.info(f"{len(self._clients)} chaves Groq carregadas")
        else:
            log.warning("GroqCouncil em modo fallback")

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def _get_state(self, symbol: str | None):
        if not symbol:
            return self.state
        if symbol not in self._states:
            self._states[symbol] = CouncilState()
        return self._states[symbol]

    def get_state(self, symbol: str = None) -> dict:
        return self._get_state(symbol).to_dict()

    def _next_client(self):
        if not self._clients:
            return None
        with self._key_lock:
            idx = self._key_idx % len(self._clients)
            self._key_idx += 1
        return self._clients.get(idx)

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    def raw_query(self, prompt: str, model: str = "main") -> str:
        if not GROQ_AVAILABLE or not self._clients:
            return "{}"

        model_map = {
            "fast": config.GROQ_MODEL_FAST,
            "main": config.GROQ_MODEL_MAIN,
            "heavy": config.GROQ_MODEL_HEAVY,
        }
        model_id = model_map.get(model, config.GROQ_MODEL_MAIN)
        client = self._next_client()
        if not client:
            return "{}"

        self._rate_limit()
        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=350
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning(f"Groq erro: {e}")
            return "{}"

    def _agent_analyzer(self, analysis: dict, price: float, sentiment: float, symbol: str = None) -> dict:
        ind = analysis.get("indicators", {})
        prompt = f"""Analise o ativo {symbol or 'UNKNOWN'}.
Preço: {price}
RSI: {ind.get('rsi')}
MACD: {ind.get('macd')}
MACD Signal: {ind.get('macd_signal')}
ADX: {ind.get('adx')}
EMA9: {ind.get('ema9')}
EMA21: {ind.get('ema21')}
EMA50: {ind.get('ema50')}
ATR: {ind.get('atr')}
StochRSI: {ind.get('stoch_rsi')}
Sentimento: {sentiment}
Score ensemble: {analysis.get('score', 0)}
Ação ensemble: {analysis.get('action', 'HOLD')}

Responda SOMENTE JSON:
{{
  "regime": "trending_up|trending_down|ranging|volatile",
  "bias": "bullish|bearish|neutral",
  "strength": 0,
  "key_signal": "frase curta"
}}"""
        try:
            return json.loads(self.raw_query(prompt, model="fast"))
        except Exception:
            score = float(analysis.get("score", 0))
            return {
                "regime": "trending_up" if score > 2.2 else "trending_down" if score < -2.2 else "ranging",
                "bias": "bullish" if score > 0.8 else "bearish" if score < -0.8 else "neutral",
                "strength": min(10, int(abs(score) * 2)),
                "key_signal": "fallback local"
            }

    def _agent_validator(self, analysis: dict, analyzer_out: dict, price: float, atr: float, symbol: str = None) -> dict:
        score = float(analysis.get("score", 0))
        action = analysis.get("action", "HOLD")
        confidence = int(analysis.get("confidence", 0))
        regime = analyzer_out.get("regime", "ranging")
        bias = analyzer_out.get("bias", "neutral")

        atr_pct = (atr / price) if price > 0 and atr else 0.0

        veto = False
        reason = ""
        conf_mult = 1.0
        threshold_adj = 0
        final_action = action

        if abs(score) < 1.2:
            veto = True
            reason = "score muito fraco"
        elif confidence < 38 and action != "HOLD":
            veto = True
            reason = "confiança insuficiente"
        elif atr_pct > 0.05:
            veto = True
            reason = "volatilidade extrema"
        elif regime == "ranging" and abs(score) < 2.2:
            veto = True
            reason = "range sem edge"

        if not veto:
            if regime in ("trending_up", "trending_down"):
                conf_mult += 0.10
            if bias == "bullish" and action == "BUY":
                conf_mult += 0.08
            if bias == "bearish" and action == "SELL":
                conf_mult += 0.08
            if regime == "ranging":
                threshold_adj -= 4
            elif regime in ("trending_up", "trending_down"):
                threshold_adj -= 4

        if veto:
            final_action = "HOLD"

        return {
            "veto": veto,
            "veto_reason": reason,
            "confidence_multiplier": round(conf_mult, 3),
            "threshold_adjustment": threshold_adj,
            "final_action": final_action
        }

    def _agent_explainer(self, analysis: dict, validator_out: dict, analyzer_out: dict,
                         price: float, symbol: str = None) -> str:
        action = validator_out.get("final_action", "HOLD")
        veto = validator_out.get("veto", False)
        reason = validator_out.get("veto_reason", "")
        regime = analyzer_out.get("regime", "")
        conf = analysis.get("confidence", 0)
        if veto:
            return f"{symbol}: {action} por veto de risco. Motivo: {reason}. Regime {regime}. Confiança base {conf}%."
        return f"{symbol}: {action} alinhado ao regime {regime}, com confiança base de {conf}%."

    def decide(self, analysis: dict, price: float, atr: float, sentiment: float, symbol: str = None) -> dict:
        if not GROQ_AVAILABLE or not self._clients:
            return self._fallback_decide(analysis, price, symbol)

        action = analysis.get("action", "HOLD")
        base_conf = int(analysis.get("confidence", 0))
        total_score = float(analysis.get("total_score", analysis.get("score", 0)))

        cs = self._get_state(symbol)
        validator_out = None
        explanation = cs.explanation

        now = time.time()
        last_call = self._last_groq_call.get(symbol, 0)
        if last_call == 0 or (now - last_call) >= self._groq_interval:
            self._last_groq_call[symbol] = now
            analyzer_out = self._agent_analyzer(analysis, price, sentiment, symbol)
            validator_out = self._agent_validator(analysis, analyzer_out, price, atr, symbol)
            explanation = self._agent_explainer(analysis, validator_out, analyzer_out, price, symbol)

            cs.update({
                "regime": analyzer_out.get("regime", cs.regime),
                "bias": analyzer_out.get("bias", cs.bias),
                "veto": validator_out.get("veto", cs.veto),
                "veto_reason": validator_out.get("veto_reason", cs.veto_reason),
                "confidence_multiplier": validator_out.get("confidence_multiplier", cs.confidence_multiplier),
                "threshold_adjustment": validator_out.get("threshold_adjustment", cs.threshold_adjustment),
                "explanation": explanation,
            })

        if validator_out is not None:
            action = validator_out.get("final_action", action)

        raw_conf = base_conf

        if cs.regime == "trending_up" and action == "BUY":
            raw_conf += 8
        elif cs.regime == "trending_down" and action == "SELL":
            raw_conf += 8
        elif cs.regime == "ranging":
            raw_conf -= 6
        elif cs.regime == "volatile":
            raw_conf -= 8

        if cs.bias == "bullish" and action == "BUY":
            raw_conf += 5
        elif cs.bias == "bearish" and action == "SELL":
            raw_conf += 5

        final_conf = int(max(0, min(100, raw_conf * cs.confidence_multiplier)))

        threshold = int(getattr(config, "CONFIDENCE_THRESHOLD", 52) + cs.threshold_adjustment)
        threshold = max(30, min(75, threshold))

        if cs.veto and action in ("BUY", "SELL"):
            action = "HOLD"
            final_conf = min(final_conf, 45)

        # note: basic low-score veto handled inside validator

        if action in ("BUY", "SELL") and final_conf < threshold:
            action = "HOLD"

        return {
            "action": action,
            "confidence": final_conf,
            "threshold": threshold,
            "total_score": total_score,
            "regime": cs.regime,
            "bias": cs.bias,
            "veto": cs.veto,
            "veto_reason": cs.veto_reason,
            "explanation": explanation,
        }

    def _fallback_decide(self, analysis: dict, price: float, symbol: str = None) -> dict:
        score = float(analysis.get("score", 0))
        conf = int(analysis.get("confidence", 0))
        action = analysis.get("action", "HOLD")

        veto = abs(score) < 1.2
        if veto:
            action = "HOLD"

        regime = "trending_up" if score > 2.2 else "trending_down" if score < -2.2 else "ranging"
        bias = "bullish" if score > 0.8 else "bearish" if score < -0.8 else "neutral"
        reason = "score muito fraco" if veto else ""
        explanation = f"{symbol}: {action} | score={score:.2f} | conf={conf}% | regime={regime}"

        cs = self._get_state(symbol)
        cs.update({
            "regime": regime,
            "bias": bias,
            "veto": veto,
            "veto_reason": reason,
            "confidence_multiplier": 1.0,
            "threshold_adjustment": 0,
            "explanation": explanation,
        })

        return {
            "action": action,
            "confidence": conf,
            "threshold": getattr(config, "CONFIDENCE_THRESHOLD", 52),
            "total_score": score,
            "regime": regime,
            "bias": bias,
            "veto": veto,
            "veto_reason": reason,
            "explanation": explanation,
        }