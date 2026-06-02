"""
Groq Council — Multi-agente de decisão com rotação de chaves,
regime detection, veto, bias e explicação em português
"""
import time
import json
import threading
import random
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
    log.warning("groq SDK não instalado. Decisões serão baseadas só no ensemble.")

# ── Estado interno do council ─────────────────────────────────

class CouncilState:
    def __init__(self):
        self.regime               = "ranging"   # trending_up|trending_down|ranging|volatile
        self.bias                 = "neutral"   # bullish|bearish|neutral
        self.veto                 = False
        self.veto_reason          = ""
        self.confidence_multiplier= 1.0
        self.threshold_adjustment = 0
        self.explanation          = ""
        self.last_updated         = ""
        self._lock                = threading.Lock()

    def update(self, data: dict):
        with self._lock:
            self.regime                = data.get("regime",               self.regime)
            self.bias                  = data.get("bias",                 self.bias)
            self.veto                  = data.get("veto",                 False)
            self.veto_reason           = data.get("veto_reason",          "")
            self.confidence_multiplier = data.get("confidence_multiplier",1.0)
            self.threshold_adjustment  = data.get("threshold_adjustment", 0)
            self.explanation           = data.get("explanation",          "")
            self.last_updated          = time.strftime("%H:%M:%S")

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "regime"               : self.regime,
                "bias"                 : self.bias,
                "veto"                 : self.veto,
                "veto_reason"          : self.veto_reason,
                "confidence_multiplier": self.confidence_multiplier,
                "threshold_adjustment" : self.threshold_adjustment,
                "explanation"          : self.explanation,
                "last_updated"         : self.last_updated,
            }


class GroqCouncil:
    """
    Três agentes Groq:
    - Analyzer   : lê indicadores e dá score + regime
    - Validator  : valida o sinal, decide veto e confiança
    - Explainer  : gera explicação legível em PT-BR
    """

    def __init__(self):
        self.state       = CouncilState()
        self._key_idx    = 0
        self._key_lock   = threading.Lock()
        self._running    = False
        self._clients    = {}
        self._last_call       = 0
        self._min_interval    = 2.5   # seg entre chamadas (evita 429)
        self._last_groq_call  = {}
        self._groq_interval   = 60    # chama o Groq só 1x por minuto por símbolo
        self._context_window  = {}    # contexto por símbolo
        self._states          = {}

        if GROQ_AVAILABLE and config.GROQ_API_KEYS:
            for i, key in enumerate(config.GROQ_API_KEYS):
                self._clients[i] = Groq(api_key=key)
            log.info(f"GroqCouncil: {len(self._clients)} chaves carregadas")
        else:
            log.warning("GroqCouncil sem clientes Groq — modo fallback")

    def start(self):
        self._running = True
        log.info("GroqCouncil iniciado")

    def stop(self):
        self._running = False

    # ── Rotação de chaves ─────────────────────────────────────

    def _next_client(self):
        with self._key_lock:
            idx = self._key_idx % len(self._clients)
            self._key_idx += 1
        return self._clients.get(idx)

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    def _get_state(self, symbol: str):
        if not symbol:
            return self.state
        if symbol not in self._states:
            self._states[symbol] = CouncilState()
        return self._states[symbol]

    # ── Query raw ─────────────────────────────────────────────

    def raw_query(self, prompt: str, model: str = "main") -> str:
        if not GROQ_AVAILABLE or not self._clients:
            return "{}"
        model_map = {
            "fast"  : config.GROQ_MODEL_FAST,
            "main"  : config.GROQ_MODEL_MAIN,
            "heavy" : config.GROQ_MODEL_HEAVY,
        }
        model_id = model_map.get(model, config.GROQ_MODEL_MAIN)
        client   = self._next_client()
        if not client:
            return "{}"
        self._rate_limit()
        try:
            resp = client.chat.completions.create(
                model    = model_id,
                messages = [{"role": "user", "content": prompt}],
                temperature = 0.15,
                max_tokens  = 512
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning(f"Groq raw_query erro: {e}")
            return "{}"

    # ── Agente 1: Analyzer ────────────────────────────────────

    def _agent_analyzer(self, analysis: dict, price: float,
                         sentiment: float, symbol: str = None) -> dict:
        ind  = analysis.get("indicators", {})
        prompt = f"""Você é um analista técnico especialista em crypto trading.

SÍMBOLO: {symbol or 'UNKNOWN'}
DADOS DE MERCADO:
- Preço atual: ${price:,.2f}
- RSI: {ind.get('rsi','N/A')}
- MACD: {ind.get('macd','N/A')} | Signal: {ind.get('macd_signal','N/A')}
- Bollinger: Upper=${ind.get('bb_upper','N/A')} | Lower=${ind.get('bb_lower','N/A')}
- EMA9: {ind.get('ema9','N/A')} | EMA21: {ind.get('ema21','N/A')} | EMA50: {ind.get('ema50','N/A')}
- Tendência: {ind.get('trend','N/A')}
- Volume ratio: {ind.get('vol_ratio','N/A')}
- Stoch RSI: {ind.get('stoch_rsi','N/A')}
- ATR: {ind.get('atr','N/A')}
- Sentimento notícias: {sentiment:+.2f} (-1=muito negativo, +1=muito positivo)
- Score ensemble: {analysis.get('score', 0):.2f} (-10 a +10)
- Sinal ensemble: {analysis.get('action','HOLD')}

Analise e responda em JSON SOMENTE (sem markdown):
{{
  "regime": "trending_up|trending_down|ranging|volatile",
  "bias": "bullish|bearish|neutral",
  "strength": 0-10,
  "key_signal": "descreva em 1 frase o sinal principal"
}}"""

        try:
            raw  = self.raw_query(prompt, model="fast")
            data = json.loads(raw)
            return data
        except Exception:
            return {
                "regime"    : "ranging",
                "bias"      : "neutral",
                "strength"  : 5,
                "key_signal": "Análise Groq indisponível"
            }

    # ── Agente 2: Validator ───────────────────────────────────

    def _agent_validator(self, analysis: dict, analyzer_out: dict,
                          price: float, atr: float, symbol: str = None) -> dict:
        score   = analysis.get("score", 0)
        action  = analysis.get("action", "HOLD")
        regime  = analyzer_out.get("regime", "ranging")
        bias    = analyzer_out.get("bias",   "neutral")
        scores  = analysis.get("scores", {})

        prompt = f"""Você é um gestor de risco de um fundo quantitativo.

SÍMBOLO: {symbol or 'UNKNOWN'}
SINAL PROPOSTO: {action}
Score ensemble: {score:.2f}
Regime de mercado: {regime}
Bias: {bias}
Scores por estratégia: {json.dumps(scores)}
ATR (volatilidade): {atr:.2f}
Preço: ${price:,.2f}

Regras de veto:
- VETAR se: regime=ranging E score < 6
- VETAR se: score < 3 (sinal fraco)
- VETAR se: ATR > 2% do preço (volatilidade extrema sem confirmaçao)
- VETAR se: bias=bearish E action=BUY E regime≠trending_up
- REDUZIR confiança se estratégias divergem muito

Responda JSON SOMENTE:
{{
  "veto": true|false,
  "veto_reason": "motivo se veto, senão vazio",
  "confidence_multiplier": 0.5-1.5,
  "threshold_adjustment": -10 a +10,
  "final_action": "BUY|SELL|HOLD"
}}"""

        try:
            raw  = self.raw_query(prompt, model="main")
            data = json.loads(raw)
            return data
        except Exception:
            # Fallback lógico sem Groq
            veto   = abs(score) < 3 or (regime == "ranging" and abs(score) < 6)
            return {
                "veto"                 : veto,
                "veto_reason"          : "Score insuficiente" if veto else "",
                "confidence_multiplier": 1.0,
                "threshold_adjustment" : 0,
                "final_action"         : "HOLD" if veto else action
            }

    # ── Agente 3: Explainer ───────────────────────────────────

    def _agent_explainer(self, analysis: dict, validator_out: dict,
                          analyzer_out: dict, price: float, symbol: str = None) -> str:
        action  = validator_out.get("final_action", "HOLD")
        veto    = validator_out.get("veto", False)
        regime  = analyzer_out.get("key_signal", "")
        conf    = analysis.get("confidence", 0)

        prompt = f"""Você é um assistente de trading. Explique em 2-3 frases curtas em português 
por que o sistema decidiu: {action} {'(VETADO)' if veto else ''}

SÍMBOLO: {symbol or 'UNKNOWN'}
Contexto:
- Sinal chave: {regime}
- Confiança: {conf}%
- Preço: ${price:,.2f}
- Veto: {'Sim — ' + validator_out.get('veto_reason','') if veto else 'Não'}

Seja direto e técnico. Não use markdown."""

        try:
            return self.raw_query(prompt, model="fast")
        except Exception:
            return f"Decisão: {action} | Regime: {analyzer_out.get('regime','?')} | Conf: {conf}%"

    # ── Decisão principal ─────────────────────────────────────

    def decide(self, analysis: dict, price: float, atr: float, sentiment: float, symbol: str = None) -> dict:
        """
        Combina score do ensemble com análise do Groq.
        O ensemble define a ação e confiança base.
        O Groq ajusta o regime, bias, veto e explica por par.
        """
        # Se não houver Groq funcional, use fallback para manter o estado consistente.
        if not GROQ_AVAILABLE or not self._clients:
            return self._fallback_decide(analysis, price, symbol)

        action     = analysis.get("action", "HOLD")
        base_conf  = analysis.get("confidence", 0)   # confiança REAL do ensemble
        total_score= analysis.get("total_score", analysis.get("score", 0))

        cs = self._get_state(symbol)
        validator_out = None

        now = time.time()
        last_call = self._last_groq_call.get(symbol, 0)
        if (now - last_call) >= self._groq_interval:
            self._last_groq_call[symbol] = now
            analyzer_out = self._agent_analyzer(analysis, price, sentiment, symbol)
            validator_out = self._agent_validator(analysis, analyzer_out, price, atr, symbol)
            explanation = self._agent_explainer(analysis, validator_out, analyzer_out, price, symbol)

            cs.update({
                "regime"               : analyzer_out.get("regime", cs.regime),
                "bias"                 : analyzer_out.get("bias", cs.bias),
                "veto"                 : validator_out.get("veto", cs.veto),
                "veto_reason"          : validator_out.get("veto_reason", cs.veto_reason),
                "confidence_multiplier": validator_out.get("confidence_multiplier", cs.confidence_multiplier),
                "threshold_adjustment" : validator_out.get("threshold_adjustment", cs.threshold_adjustment),
                "explanation"          : explanation,
            })
        else:
            explanation = cs.explanation

        if validator_out is not None:
            action = validator_out.get("final_action", action)

        raw_conf = base_conf
        if cs.regime == "trending_up" and action == "BUY":
            raw_conf = min(100, raw_conf + 10)
        elif cs.regime == "trending_down" and action == "BUY":
            raw_conf = max(0, raw_conf - 15)
        elif cs.regime == "volatile":
            raw_conf = max(0, raw_conf - 10)

        if cs.bias == "bearish" and action == "BUY":
            raw_conf = max(0, raw_conf - 10)
        elif cs.bias == "bullish" and action == "BUY":
            raw_conf = min(100, raw_conf + 5)

        final_conf = int(raw_conf * cs.confidence_multiplier)
        final_conf = max(0, min(100, final_conf))

        threshold = getattr(config, "CONFIDENCE_THRESHOLD", 60)
        threshold += cs.threshold_adjustment
        threshold = max(0, min(100, threshold))

        if cs.veto and action in ("BUY", "SELL"):
            action = "HOLD"
            final_conf = min(final_conf, 40)

        if abs(total_score) < 3:
            action = "HOLD"

        if action in ("BUY", "SELL") and final_conf < threshold:
            action = "HOLD"

        return {
            "action"     : action,
            "confidence" : final_conf,
            "threshold"  : threshold,
            "total_score": total_score,
            "regime"     : cs.regime,
            "bias"       : cs.bias,
            "veto"       : cs.veto,
            "veto_reason": cs.veto_reason,
            "explanation": explanation,
        }


    def _async_groq_analysis(self, analysis: dict, price: float,
                            atr: float, sentiment: float, symbol: str = None):
        """Roda análise Groq em background — só atualiza regime/bias/explicação."""
        try:
            scores = analysis.get("scores", {})
            last   = analysis.get("indicators", {})
            prompt = (
                f"MARKET: {symbol or 'UNKNOWN'}\n"
                f"Análise de mercado crypto para trading por símbolo\n"
                f"Preço: ${price:,.2f} | ATR: {atr:.2f} | Sentimento: {sentiment:.2f}\n"
                f"Indicadores: RSI={last.get('rsi','?')} | MACD={last.get('macd','?')} "
                f"| Trend={last.get('trend','?')}\n"
                f"Scores: TrendFollow={scores.get('trend',0)} "
                f"MeanReversion={scores.get('mean_reversion',0)} "
                f"Breakout={scores.get('breakout',0)} "
                f"Momentum={scores.get('momentum',0)}\n"
                f"Objetivo: buscar setups de maior assertividade e oportunidades claras, "
                f"apoiando apenas entradas fortes e evitando excesso de risco.\n"
                f"Responda APENAS com JSON válido (sem markdown):\n"
                f'{{"regime":"trending_up|trending_down|ranging|volatile",'
                f'"bias":"bullish|bearish|neutral",'
                f'"veto":false,'
                f'"veto_reason":"",'
                f'"confidence_multiplier":1.0,'
                f'"threshold_adjustment":0,'
                f'"explanation":"máximo 200 chars em português"}}'
            )
            raw  = self.raw_query(prompt, model="fast")

            # Extrai JSON da resposta
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                # NÃO usa confidence do Groq — usa só regime/bias/veto/explicação
                data.pop("confidence", None)
                self._get_state(symbol).update(data)
        except Exception as e:
            log.debug(f"Async Groq falhou: {e}")

    def _fallback_decide(self, analysis: dict, price: float, symbol: str = None) -> dict:
        """Decisão puramente baseada no ensemble sem Groq."""
        action = analysis.get("action", "HOLD")
        score  = analysis.get("score",  0)
        conf   = analysis.get("confidence", 0)

        # Veto por score fraco
        if abs(score) < 4:
            action = "HOLD"
            veto   = True
            reason = f"Score fraco ({score:.1f})"
        else:
            veto   = False
            reason = ""

        regime = "trending_up"   if score > 5  else \
                 "trending_down" if score < -5 else \
                 "ranging"
        bias   = "bullish" if score > 0 else ("bearish" if score < 0 else "neutral")

        cs = self._get_state(symbol)
        cs.update({
            "regime"               : regime,
            "bias"                 : bias,
            "veto"                 : veto,
            "veto_reason"          : reason,
            "confidence_multiplier": 1.0,
            "threshold_adjustment" : 0,
            "explanation"          : f"[Fallback] {action} | Score={score:.1f} | Conf={conf}%",
        })
        return {
            "action"               : action,
            "confidence"           : conf,
            "regime"               : regime,
            "bias"                 : bias,
            "veto"                 : veto,
            "veto_reason"          : reason,
            "confidence_multiplier": 1.0,
            "threshold_adjustment" : 0,
            "explanation"          : f"Score={score:.1f} — decisão automática sem Groq",
        }

    def get_state(self, symbol: str = None) -> dict:
        return self._get_state(symbol).to_dict()