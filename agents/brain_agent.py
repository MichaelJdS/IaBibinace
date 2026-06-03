"""
Brain Agent v3 — Multi-mercado: Crypto + Forex
- Usa MarketDataHub em vez de BinanceWS diretamente
- Roteamento automático de executor por tipo de mercado
- Alta frequência: CYCLE_SLEEP = 1s
"""
import time
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils.logger import get_logger
from utils.telegram_notifier import (
    start as tg_start, stop as tg_stop,
    notify_buy, notify_sell, notify_regime_change,
    notify_daily_summary, notify_error,
    notify_daily_loss_limit, notify_cooldown
)
from core.binance_ws      import BinanceWebSocketManager
from core.market_data_hub import MarketDataHub
from core.indicators      import TechnicalIndicators
from core.order_executor  import OrderExecutor
from core.forex_executor  import ForexExecutor
from core.news_engine     import NewsEngine
from core.database        import DatabaseEngine
from core.adaptive_engine import AdaptiveEngine
from core.risk_engine     import RiskEngine
from core.groq_council    import GroqCouncil
from strategies.ensemble  import EnsembleStrategy

log = get_logger("Brain")


class BrainAgent:
    def __init__(self):
        log.info("=== CRYPTO IA BOT v3 — Multi-mercado iniciando ===")

        self.db         = DatabaseEngine()
        self._binance_ws = BinanceWebSocketManager()
        self.ws         = MarketDataHub(self._binance_ws)
        self.indicators = TechnicalIndicators()
        self.news       = NewsEngine()
        self.groq       = GroqCouncil()
        self.adaptive   = AdaptiveEngine(self.db, self.groq)
        self.risk       = RiskEngine(self.db, self.adaptive)

        self.crypto_executor = OrderExecutor()
        self.forex_executor  = ForexExecutor()

        self.ensemble = EnsembleStrategy(self.adaptive)

        self._running             = False
        self._session_id          = None
        self._cycle               = 0
        self._last_analysis       = {}
        self._last_regime_by_pair = {}
        self._last_summary_hour   = -1
        self._pair_contexts       = {}  # cache de contexto MTF por par

    def _get_executor(self, symbol: str):
        if config.MARKET_TYPE_MAP.get(symbol) == "forex":
            return self.forex_executor
        return self.crypto_executor

    def start(self):
        self._running    = True
        self._session_id = self.db.start_session(config.TRADING_MODE)

        self.ws.start()
        self.news.start()
        self.groq.start()
        tg_start()

        self.crypto_executor.set_ws(self._binance_ws)
        self.forex_executor.set_hub(self.ws)

        bal = self.crypto_executor.get_balance("USDT")
        self.risk.set_daily_start_balance(bal)

        log.info("Aguardando dados iniciais...")
        time.sleep(5)
        self._main_loop()

    def stop(self):
        self._running = False
        try:
            stats = self.risk.get_stats()
            bal   = self.crypto_executor.get_balance("USDT")
            notify_daily_summary(stats, bal)
        except Exception:
            pass

        self.ws.stop()
        self.news.stop()
        self.groq.stop()
        tg_stop()

        if self._session_id:
            stats = self.risk.get_stats()
            self.db.end_session(self._session_id, stats["trades"], stats["total_pnl"])

        log.info("Brain parado.")

    def _main_loop(self):
        log.info("Loop principal v3 iniciado")
        while self._running:
            try:
                self._cycle += 1
                self._run_cycle()
                self._check_daily_summary()
            except Exception as e:
                log.error(f"Erro ciclo {self._cycle}: {e}", exc_info=True)
                if self._cycle % 10 == 0:
                    notify_error("Brain", str(e)[:200])
            time.sleep(getattr(config, "CYCLE_SLEEP", 1.0))

    def _check_daily_summary(self):
        hour = int(time.strftime("%H"))
        if hour == 23 and self._last_summary_hour != 23:
            stats = self.risk.get_stats()
            bal   = self.crypto_executor.get_balance("USDT")
            notify_daily_summary(stats, bal)
            self._last_summary_hour = 23
        elif hour != 23:
            self._last_summary_hour = hour

    def _run_cycle(self):
        for pair in config.TRADING_PAIRS:
            if not self.ws.is_ready(pair):
                continue
            try:
                self._process_pair(pair)
            except Exception as e:
                log.error(f"Erro par {pair}: {e}", exc_info=True)

    def _build_context(self, pair: str) -> dict:
        """Constrói contexto MTF para melhorar score do ensemble."""
        context = {}
        df_primary = self.ws.get_candles(pair, config.TF_PRIMARY)
        if not df_primary.empty and len(df_primary) >= 50:
            df_ind = self.indicators.compute_all(df_primary.copy())
            trend = str(df_ind.iloc[-1].get("trend", ""))
            context["primary_trend"] = trend

        df_confirm = self.ws.get_candles(pair, config.TF_CONFIRM)
        if not df_confirm.empty and len(df_confirm) >= 50:
            df_ind = self.indicators.compute_all(df_confirm.copy())
            context["confirm_trend"] = str(df_ind.iloc[-1].get("trend", ""))

        regime = self.groq.get_state(symbol=pair).get("regime", "ranging")
        context["market_regime"] = regime
        return context

    def _process_pair(self, pair: str):
        price = self.ws.get_price(pair)
        if price <= 0:
            return

        df = self.ws.get_candles(pair, config.TF_PRIMARY)
        if df.empty or len(df) < 50:
            return

        df_ind = self.indicators.compute_all(df.copy())
        last   = df_ind.iloc[-1]

        if self._cycle % 10 == 0:
            self.db.save_snapshot({
                "symbol":    pair,
                "price":     price,
                "rsi":       last.get("rsi"),
                "macd":      last.get("macd"),
                "bb_width":  last.get("bb_width"),
                "trend":     last.get("trend"),
                "volume":    last.get("volume"),
                "sentiment": self.news.get_sentiment(pair.replace("USDT", "").replace("USD", ""))
            })

        executor = self._get_executor(pair)
        pos = executor.get_open_position(pair)

        if pos:
            sl_hit = price <= pos["stop_loss"]
            tp_hit = price >= pos["take_profit"]
            tr_hit = self.risk.check_trailing_stop(pos, price)

            if sl_hit or tp_hit or tr_hit:
                reason = "sl" if sl_hit else ("tp" if tp_hit else "trailing")
                result = executor.sell(symbol=pair, reason=reason)
                ok, pnl_pct, pnl_usd, is_win = result
                if ok:
                    entry    = pos["entry_price"]
                    duration = int(time.time() - pos.get("entry_time", time.time()))
                    self.risk.record_trade(
                        pnl_usd=pnl_usd, pnl_pct=pnl_pct, is_win=is_win,
                        reason=reason,
                        trade_id=getattr(executor, "_last_trade_id", None),
                        exit_price=price, duration_sec=duration
                    )
                    notify_sell(
                        symbol=pair, entry=entry, exit_p=price,
                        qty=pos["quantity"], pnl_usd=pnl_usd,
                        pnl_pct=pnl_pct * 100, reason=reason,
                        duration_sec=duration
                    )
            return

        open_count  = len(executor.get_open_positions())
        can, reason = self.risk.can_trade(open_count)
        if not can:
            if "Cooldown" in reason and self._cycle % 40 == 0:
                notify_cooldown(reason, 0)
            return

        # MTF context (atualiza a cada 5 ciclos por par)
        if self._cycle % 5 == 0:
            self._pair_contexts[pair] = self._build_context(pair)
        context = self._pair_contexts.get(pair, {})

        sentiment = self.news.get_sentiment(pair.replace("USDT", "").replace("USD", ""))
        analysis  = self.ensemble.analyze(df_ind, sentiment, context=context)
        self._last_analysis = analysis

        atr      = float(last.get("atr", 0) or 0)
        decision = self.groq.decide(analysis, price, atr, sentiment, symbol=pair)

        new_regime = decision.get("regime", "ranging")
        if new_regime != self._last_regime_by_pair.get(pair):
            notify_regime_change(
                old_regime=self._last_regime_by_pair.get(pair, "ranging"),
                new_regime=new_regime,
                price=price,
                symbol=pair
            )
            self._last_regime_by_pair[pair] = new_regime

        self.db.save_ai_decision({
            **decision,
            "symbol":     pair,
            "indicators": analysis.get("indicators", {})
        })

        if decision["action"] == "BUY":
            bal    = executor.get_balance("USDT")
            qty    = self.risk.compute_position_size(bal, price, atr)
            sl, tp = self.risk.compute_sl_tp(price, atr)

            ok = executor.buy(
                symbol=pair, quantity=qty, price=price,
                stop_loss=sl, take_profit=tp
            )
            if ok:
                trade_id = self.db.save_trade_open({
                    "symbol":       pair,
                    "side":         "BUY",
                    "entry_price":  price,
                    "quantity":     qty,
                    "stop_loss":    sl,
                    "take_profit":  tp,
                    "reason_entry": decision.get("explanation", "")[:200],
                    "confidence":   decision.get("confidence"),
                    "regime":       decision.get("regime"),
                    "indicators":   analysis.get("indicators", {}),
                    "mode":         config.TRADING_MODE
                })
                executor._last_trade_id = trade_id
                notify_buy(
                    symbol=pair, price=price, qty=qty,
                    sl=sl, tp=tp,
                    confidence=decision.get("confidence", 0),
                    regime=decision.get("regime", ""),
                    explanation=decision.get("explanation", "")
                )
                log.info(
                    f"🟢 {pair} BUY @ {price:.4f} | "
                    f"conf={decision['confidence']}% | regime={decision.get('regime','?')} | "
                    f"SL={sl:.4f} TP={tp:.4f}"
                )

        elif decision["action"] == "SELL" and config.ALLOW_SHORTS:
            log.info(
                f"🔴 {pair} SELL @ {price:.4f} | "
                f"conf={decision['confidence']}% | regime={decision.get('regime','?')}"
            )