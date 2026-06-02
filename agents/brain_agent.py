"""
Brain Agent v2 — Orquestra todos os componentes do bot
BUGS CORRIGIDOS:
  - sell() resultado sempre tratado como tupla
  - checagem dupla de pos removida
  - record_trade() recebe exit_price e duration_sec reais
  - executor.set_ws() chamado para preço real no demo
"""
import time
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils.logger            import get_logger
from utils.telegram_notifier import (
    start as tg_start, stop as tg_stop,
    notify_buy, notify_sell, notify_regime_change,
    notify_daily_summary, notify_error,
    notify_daily_loss_limit, notify_cooldown
)
from core.binance_ws     import BinanceWebSocketManager
from core.indicators     import TechnicalIndicators
from core.order_executor import OrderExecutor
from core.news_engine    import NewsEngine
from core.database       import DatabaseEngine
from core.adaptive_engine import AdaptiveEngine
from core.risk_engine    import RiskEngine
from core.groq_council   import GroqCouncil
from strategies.ensemble import EnsembleStrategy

log = get_logger("Brain")


class BrainAgent:
    def __init__(self):
        log.info("=== CRYPTO IA BOT v2 — Inicializando Brain ===")

        self.db        = DatabaseEngine()
        self.ws        = BinanceWebSocketManager()
        self.indicators= TechnicalIndicators()
        self.news      = NewsEngine()
        self.groq      = GroqCouncil()
        self.adaptive  = AdaptiveEngine(self.db, self.groq)
        self.risk      = RiskEngine(self.db, self.adaptive)
        self.executor  = OrderExecutor()
        self.ensemble  = EnsembleStrategy(self.adaptive)

        self._running             = False
        self._session_id          = None
        self._cycle               = 0
        self._last_analysis       = {}
        self._last_regime_by_pair = {}
        self._last_summary_hour   = -1

    # ── Start / Stop ──────────────────────────────────────────

    def start(self):
        log.info("Brain.start() chamado")
        self._running    = True
        self._session_id = self.db.start_session(config.TRADING_MODE)

        self.ws.start()
        self.news.start()
        self.groq.start()
        tg_start()

        # FIX: passa referência ao WS para executor usar preço real em demo
        self.executor.set_ws(self.ws)

        bal = self.executor.get_balance("USDT")
        self.risk.set_daily_start_balance(bal)

        log.info("Aguardando dados iniciais do WebSocket...")
        time.sleep(5)
        self._main_loop()

    def stop(self):
        log.info("Brain.stop() chamado")
        self._running = False
        try:
            stats = self.risk.get_stats()
            bal   = self.executor.get_balance("USDT")
            notify_daily_summary(stats, bal)
        except Exception:
            pass

        self.ws.stop()
        self.news.stop()
        self.groq.stop()
        tg_stop()

        if self._session_id:
            stats = self.risk.get_stats()
            self.db.end_session(
                self._session_id,
                stats["trades"],
                stats["total_pnl"]
            )
        log.info("Brain parado com segurança.")

    # ── Loop principal ────────────────────────────────────────

    def _main_loop(self):
        log.info("Loop principal iniciado")
        while self._running:
            try:
                self._cycle += 1
                self._run_cycle()
                self._check_daily_summary()
            except Exception as e:
                log.error(f"Erro no ciclo {self._cycle}: {e}", exc_info=True)
                if self._cycle % 10 == 0:
                    notify_error("Brain", str(e)[:200])
            time.sleep(getattr(config, "CYCLE_SLEEP", 3))

    def _check_daily_summary(self):
        hour = int(time.strftime("%H"))
        if hour == 23 and self._last_summary_hour != 23:
            stats = self.risk.get_stats()
            bal   = self.executor.get_balance("USDT")
            notify_daily_summary(stats, bal)
            self._last_summary_hour = 23
        elif hour != 23:
            self._last_summary_hour = hour

    # ── Ciclo de trading ──────────────────────────────────────

    def _run_cycle(self):
        for pair in config.TRADING_PAIRS:
            try:
                self._process_pair(pair)
            except Exception as e:
                log.error(f"Erro no par {pair}: {e}", exc_info=True)

    def _process_pair(self, pair: str):
        price = self.ws.get_price(pair)
        if price <= 0:
            return

        df = self.ws.get_candles(pair, config.TF_PRIMARY)
        if df.empty or len(df) < 30:
            return

        df_ind = self.indicators.compute_all(df.copy())
        last   = df_ind.iloc[-1]

        if self._cycle % 10 == 0:
            self.db.save_snapshot({
                "symbol"   : pair,
                "price"    : price,
                "rsi"      : last.get("rsi"),
                "macd"     : last.get("macd"),
                "bb_width" : last.get("bb_width"),
                "trend"    : last.get("trend"),
                "volume"   : last.get("volume"),
                "sentiment": self.news.get_sentiment(pair[:-4])
            })

        # ── Gerencia posição aberta ───────────────────────────
        pos = self.executor.get_open_position(pair)
        if pos:
            sl_hit = price <= pos["stop_loss"]
            tp_hit = price >= pos["take_profit"]
            tr_hit = self.risk.check_trailing_stop(pos, price)

            if sl_hit or tp_hit or tr_hit:
                reason = "sl" if sl_hit else ("tp" if tp_hit else "trailing")
                result = self.executor.sell(symbol=pair, reason=reason)

                # FIX: result é sempre tupla agora
                ok, pnl_pct, pnl_usd, is_win = result
                if ok:
                    entry    = pos["entry_price"]
                    duration = int(time.time() - pos.get("entry_time", time.time()))

                    # FIX: passa exit_price e duration reais para o banco
                    self.risk.record_trade(
                        pnl_usd      = pnl_usd,
                        pnl_pct      = pnl_pct,
                        is_win       = is_win,
                        reason       = reason,
                        trade_id     = getattr(self.executor, "_last_trade_id", None),
                        exit_price   = price,
                        duration_sec = duration
                    )

                    notify_sell(
                        symbol       = pair,
                        entry        = entry,
                        exit_p       = price,
                        qty          = pos["quantity"],
                        pnl_usd      = pnl_usd,
                        pnl_pct      = pnl_pct * 100,
                        reason       = reason,
                        duration_sec = duration
                    )

                    stats = self.risk.get_stats()
                    loss_limit = self.risk.daily_start_bal * config.MAX_DAILY_LOSS_PCT
                    if abs(stats["daily_loss"]) >= loss_limit and stats["daily_loss"] < 0:
                        notify_daily_loss_limit(100.0, stats["daily_loss"])
            return   # sai após processar posição aberta

        # ── Verifica se pode abrir nova posição ───────────────
        open_count  = len(self.executor.get_open_positions())
        can, reason = self.risk.can_trade(open_count)
        if not can:
            if self._cycle % 20 == 0:
                log.debug(f"Trade bloqueado ({pair}): {reason}")
            if "Cooldown" in reason and self._cycle % 40 == 0:
                notify_cooldown(reason, 0)
            return

        # ── Análise e decisão ─────────────────────────────────
        sentiment = self.news.get_sentiment(pair[:-4])
        analysis  = self.ensemble.analyze(df_ind, sentiment)
        self._last_analysis = analysis

        atr      = float(last.get("atr", 0) or 0)
        decision = self.groq.decide(analysis, price, atr, sentiment, symbol=pair)

        # Detecta mudança de regime
        new_regime = decision.get("regime", "ranging")
        if new_regime != self._last_regime_by_pair.get(pair):
            notify_regime_change(
                old_regime = self._last_regime_by_pair.get(pair, "ranging"),
                new_regime = new_regime,
                price      = price,
                symbol     = pair
            )
            self._last_regime_by_pair[pair] = new_regime

        self.db.save_ai_decision({
            **decision,
            "symbol"    : pair,
            "indicators": analysis.get("indicators", {})
        })

        # ── Executa BUY ───────────────────────────────────────
        if decision["action"] == "BUY":
            bal    = self.executor.get_balance("USDT")
            qty    = self.risk.compute_position_size(bal, price, atr)
            sl, tp = self.risk.compute_sl_tp(price, atr)

            ok = self.executor.buy(
                quantity   = qty,
                price      = price,
                symbol     = pair,
                stop_loss  = sl,
                take_profit= tp
            )
            if ok:
                trade_id = self.db.save_trade_open({
                    "symbol"      : pair,
                    "side"        : "BUY",
                    "entry_price" : price,
                    "quantity"    : qty,
                    "stop_loss"   : sl,
                    "take_profit" : tp,
                    "reason_entry": decision.get("explanation", "")[:200],
                    "confidence"  : decision.get("confidence"),
                    "regime"      : decision.get("regime"),
                    "indicators"  : analysis.get("indicators", {}),
                    "mode"        : config.TRADING_MODE
                })
                self.executor._last_trade_id = trade_id

                notify_buy(
                    symbol      = pair,
                    price       = price,
                    qty         = qty,
                    sl          = sl,
                    tp          = tp,
                    confidence  = decision.get("confidence", 0),
                    regime      = decision.get("regime", ""),
                    explanation = decision.get("explanation", "")
                )

                log.info(
                    f"🟢 ENTRADA | {qty:.6f} {pair} @ ${price:,.2f} | "
                    f"conf={decision['confidence']}% | "
                    f"regime={decision.get('regime','?')} | "
                    f"SL=${sl:.2f} TP=${tp:.2f}"
                )