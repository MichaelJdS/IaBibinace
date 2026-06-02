"""
Adaptive Engine — Ajusta parâmetros automaticamente com base
na performance recente usando análise estatística + Groq
"""
import time
import json
import statistics
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Adaptive")

class AdaptiveEngine:
    """
    Monitora métricas de performance e ajusta:
    - RSI thresholds
    - MACD sensitivity
    - SL/TP ratio
    - Confidence threshold
    - Cooldown
    """

    def __init__(self, db_engine, groq_council=None):
        self.db         = db_engine
        self.groq       = groq_council
        self._params    = self._load_defaults()
        self._last_eval = 0
        self._eval_interval = 300   # avalia a cada 5 min
        self._min_trades    = 5     # mín de trades para adaptar

        log.info("AdaptiveEngine iniciado")

    def _load_defaults(self) -> dict:
        return {
            "rsi_oversold"      : config.RSI_OVERSOLD,
            "rsi_overbought"    : config.RSI_OVERBOUGHT,
            "stop_loss_pct"     : config.STOP_LOSS_PCT,
            "take_profit_pct"   : config.TAKE_PROFIT_PCT,
            "confidence_threshold": getattr(config, "CONFIDENCE_THRESHOLD", 60),
            "cooldown_seconds"  : config.COOLDOWN_SECONDS,
            "macd_sensitivity"  : 1.0,  # multiplicador
            "position_size_pct" : 0.8,  # % do tamanho base
        }

    def get_param(self, key: str, fallback=None):
        return self._params.get(key, fallback)

    def get_all_params(self) -> dict:
        return self._params.copy()

    # ── Loop de avaliação ─────────────────────────────────────

    def evaluate(self):
        now = time.time()
        if now - self._last_eval < self._eval_interval:
            return
        self._last_eval = now

        log.debug("Avaliando performance para adaptação...")

        # Pega trades das últimas 4h
        since   = int(now) - 4 * 3600
        trades  = self.db.get_trades(limit=100, since=since)

        if len(trades) < self._min_trades:
            log.debug(f"Trades insuficientes para adaptar ({len(trades)} < {self._min_trades})")
            return

        self._analyze_and_adjust(trades)

    def _analyze_and_adjust(self, trades: list):
        wins    = [t for t in trades if t["win"]]
        losses  = [t for t in trades if not t["win"]]
        winrate = len(wins) / len(trades)
        pnls    = [t["pnl_usd"] or 0 for t in trades]
        avg_win = statistics.mean([p for p in pnls if p > 0]) if wins  else 0
        avg_loss= statistics.mean([p for p in pnls if p < 0]) if losses else 0
        pf      = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        log.info(
            f"Análise: {len(trades)} trades | "
            f"WR={winrate*100:.1f}% | PF={pf:.2f} | "
            f"AvgW=${avg_win:.4f} | AvgL=${avg_loss:.4f}"
        )

        changes = []

        # ── Regra 1: winrate muito baixa → relaxar entradas ──
        if winrate < 0.35:
            old = self._params["confidence_threshold"]
            new = min(old + 5, 85)
            if new != old:
                self._update("confidence_threshold", old, new,
                    f"Winrate baixa ({winrate*100:.1f}%) — aumentando threshold")
                changes.append(f"confidence_threshold: {old}→{new}")

        # ── Regra 2: winrate alta → pode ser mais agressivo ──
        elif winrate > 0.65 and len(trades) >= 10:
            old = self._params["confidence_threshold"]
            new = max(old - 3, 45)
            if new != old:
                self._update("confidence_threshold", old, new,
                    f"Winrate alta ({winrate*100:.1f}%) — reduzindo threshold")
                changes.append(f"confidence_threshold: {old}→{new}")

        # ── Regra 3: profit factor ruim → ampliar TP ─────────
        if pf < 1.2 and avg_win < abs(avg_loss):
            old = self._params["take_profit_pct"]
            new = min(old * 1.1, config.TAKE_PROFIT_PCT * 2.0)
            new = round(new, 4)
            if new != old:
                self._update("take_profit_pct", old, new,
                    f"PF baixo ({pf:.2f}) — ampliando TP")
                changes.append(f"take_profit_pct: {old:.4f}→{new:.4f}")

        # ── Regra 4: muitas perdas seguidas → cooldown maior ─
        consecutive_losses = 0
        for t in sorted(trades, key=lambda x: x["entry_time"], reverse=True):
            if not t["win"]:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= 3:
            old = self._params["cooldown_seconds"]
            new = min(old + 60, 600)
            if new != old:
                self._update("cooldown_seconds", old, new,
                    f"{consecutive_losses} perdas consecutivas — aumentando cooldown")
                changes.append(f"cooldown_seconds: {old}→{new}")

        elif consecutive_losses == 0 and winrate > 0.55:
            old = self._params["cooldown_seconds"]
            new = max(old - 30, config.COOLDOWN_SECONDS)
            if new != old:
                self._update("cooldown_seconds", old, new,
                    "Performance positiva — reduzindo cooldown")
                changes.append(f"cooldown_seconds: {old}→{new}")

        # ── Regra 5: perdas médias muito grandes → reduz qty ─
        if avg_loss != 0 and abs(avg_loss) > abs(avg_win) * 1.5:
            old = self._params["position_size_pct"]
            new = max(old * 0.85, 0.4)
            new = round(new, 2)
            if new != old:
                self._update("position_size_pct", old, new,
                    "Perdas muito grandes — reduzindo tamanho de posição")
                changes.append(f"position_size_pct: {old}→{new}")

        elif winrate > 0.6 and pf > 1.5:
            old = self._params["position_size_pct"]
            new = min(old * 1.1, 1.2)
            new = round(new, 2)
            if new != old:
                self._update("position_size_pct", old, new,
                    f"Performance ótima (WR={winrate*100:.0f}%, PF={pf:.1f}) — aumentando posição")
                changes.append(f"position_size_pct: {old}→{new}")

        # ── Groq: refinamento adicional ───────────────────────
        if changes and self.groq:
            self._ask_groq_refine(trades, changes, winrate, pf)

        if changes:
            log.info(f"✅ Adaptações aplicadas: {' | '.join(changes)}")
        else:
            log.debug("Nenhuma adaptação necessária.")

    def _update(self, param: str, old, new, reason: str):
        self._params[param] = new
        self.db.log_param_change(param, old, new, reason)
        log.info(f"⚙️  {param}: {old} → {new} | {reason}")

    def _ask_groq_refine(self, trades: list, changes: list,
                          winrate: float, pf: float):
        """Pede ao Groq para validar/sugerir ajustes adicionais."""
        try:
            summary = {
                "trades"       : len(trades),
                "winrate_pct"  : round(winrate * 100, 1),
                "profit_factor": round(pf, 2),
                "changes_made" : changes,
                "current_params": self._params
            }
            prompt = f"""Você é um especialista em sistemas de trading algorítmico.

Análise de performance recente:
{json.dumps(summary, indent=2)}

Revise os ajustes automáticos feitos. Sugira (em JSON) qualquer parâmetro adicional 
que deva ser alterado. Responda SOMENTE com JSON no formato:
{{"suggestions": [{{"param": "nome", "value": 0.0, "reason": "motivo"}}]}}
Se não houver sugestões, retorne {{"suggestions": []}}"""

            resp = self.groq.raw_query(prompt, model="fast")
            data = json.loads(resp)
            for s in data.get("suggestions", []):
                param = s.get("param")
                value = s.get("value")
                reason= s.get("reason", "Groq suggestion")
                if param in self._params and value is not None:
                    old = self._params[param]
                    self._update(param, old, value, f"[GROQ] {reason}")
        except Exception as e:
            log.debug(f"Groq refine falhou: {e}")

    # ── Aplica params ao config em runtime ───────────────────

    def apply_to_runtime(self):
        """Sincroniza params adaptativos com o módulo config em runtime."""
        import config as cfg
        cfg.STOP_LOSS_PCT     = self._params["stop_loss_pct"]
        cfg.TAKE_PROFIT_PCT   = self._params["take_profit_pct"]
        cfg.COOLDOWN_SECONDS  = int(self._params["cooldown_seconds"])
        cfg.RSI_OVERSOLD      = int(self._params["rsi_oversold"])
        cfg.RSI_OVERBOUGHT    = int(self._params["rsi_overbought"])
        log.debug("Params adaptativos aplicados ao runtime config")