"""
Risk Engine — Gerenciamento de risco completo
BUGS CORRIGIDOS:
  - record_trade() agora recebe e salva exit_price e duration reais
  - cooldown só ativa em SL real, não em qualquer loss
  - check_trailing_stop() usa lock para thread safety
"""
import time
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Risk")


class RiskEngine:
    def __init__(self, db_engine=None, adaptive_engine=None):
        self.db              = db_engine
        self.adaptive        = adaptive_engine
        self._lock           = threading.Lock()
        self.daily_start_bal = 1000.0
        self._trades_today   = []
        self._wins           = 0
        self._losses         = 0
        self._total_pnl      = 0.0
        self._daily_pnl      = 0.0
        self._in_cooldown    = False
        self._cooldown_until = 0
        self._session_start  = int(time.time())
        # Referência ao executor para ler parâmetros de risco em runtime
        self._executor_ref   = None
        log.info("RiskEngine iniciado")

    def set_executor(self, executor):
        """Liga o RiskEngine ao OrderExecutor para ler SL/TP/MaxOrder em runtime."""
        self._executor_ref = executor

    # ── Setters de risco chamados pela GUI ────────────────────

    def set_stop_loss_pct(self, value: float):
        """Define SL% no config e no executor em runtime. value ex: 1.5 → 0.015"""
        pct = max(0.001, value / 100.0)
        config.STOP_LOSS_PCT = pct
        if self._executor_ref:
            self._executor_ref.set_sl_pct(pct)
        log.info(f"RiskEngine: Stop Loss → {value:.1f}%")

    def set_take_profit_pct(self, value: float):
        """Define TP% no config e no executor em runtime. value ex: 2.5 → 0.025"""
        pct = max(0.001, value / 100.0)
        config.TAKE_PROFIT_PCT = pct
        if self._executor_ref:
            self._executor_ref.set_tp_pct(pct)
        log.info(f"RiskEngine: Take Profit → {value:.1f}%")

    def set_max_order_usdt(self, value: float):
        """Define valor máximo por ordem em USDT no executor em runtime."""
        if self._executor_ref:
            self._executor_ref.set_max_order_usdt(value)
        log.info(f"RiskEngine: Max Ordem → ${value:.2f}")

    # ── Verificações de entrada ───────────────────────────────

    def can_trade(self, open_positions: int = 0) -> tuple:
        # Cooldown ativo
        if self._in_cooldown:
            remaining = self._cooldown_until - time.time()
            if remaining > 0:
                return False, f"Cooldown ativo: {int(remaining)}s restantes"
            else:
                self._in_cooldown = False
                log.info("Cooldown encerrado. Bot liberado.")

        # Limite de trades simultâneos
        max_open = getattr(config, "MAX_OPEN_TRADES", 2)
        if open_positions >= max_open:
            return False, f"Máximo de trades simultâneos: {open_positions}/{max_open}"

        # Limite de perda diária
        daily_loss_limit = self.daily_start_bal * config.MAX_DAILY_LOSS_PCT
        if abs(self._daily_pnl) >= daily_loss_limit and self._daily_pnl < 0:
            return False, f"Limite diário atingido: ${self._daily_pnl:.4f}"

        # Máximo de trades hoje
        today_trades = self._count_today_trades()
        max_day      = getattr(config, "MAX_TRADES_PER_DAY", 20)
        if today_trades >= max_day:
            return False, f"Máximo de trades diários: {today_trades}/{max_day}"

        return True, "ok"

    def _count_today_trades(self) -> int:
        today = int(time.mktime(time.strptime(
            time.strftime("%Y-%m-%d"), "%Y-%m-%d"
        )))
        return sum(1 for t in self._trades_today if t["time"] >= today)

    # ── Registro de resultados ────────────────────────────────

    def record_trade(self, pnl_usd: float, pnl_pct: float,
                     is_win: bool, reason: str,
                     trade_id: int = None,
                     exit_price: float = 0.0,
                     duration_sec: int = 0):
        """
        FIX: recebe exit_price e duration_sec reais para salvar no banco.
        FIX: cooldown só ativa se reason == 'sl' (stop loss real).
        """
        with self._lock:
            self._total_pnl += pnl_usd
            self._daily_pnl += pnl_usd

            if is_win:
                self._wins += 1
            else:
                self._losses += 1
                # FIX: cooldown APENAS em stop loss, não em trailing/sinal
                if reason == "sl":
                    cd = self.adaptive.get_param("cooldown_seconds") \
                         if self.adaptive else config.COOLDOWN_SECONDS
                    self._in_cooldown    = True
                    self._cooldown_until = time.time() + cd
                    log.warning(f"SL atingido → Cooldown {cd}s | PnL: ${pnl_usd:.4f}")
                else:
                    log.info(f"Trade encerrado por '{reason}' sem cooldown | PnL: ${pnl_usd:.4f}")

            self._trades_today.append({
                "time"    : int(time.time()),
                "pnl_usd" : pnl_usd,
                "pnl_pct" : pnl_pct,
                "win"     : is_win,
                "reason"  : reason
            })

        # FIX: salva exit_price e duration reais no banco
        if self.db and trade_id:
            self.db.save_trade_close(trade_id, {
                "pnl_usd"     : pnl_usd,
                "pnl_pct"     : pnl_pct,
                "reason"      : reason,
                "exit_price"  : exit_price,
                "duration_sec": duration_sec
            })

        if self.adaptive:
            self.adaptive.evaluate()
            self.adaptive.apply_to_runtime()

    def set_daily_start_balance(self, balance: float):
        self.daily_start_bal = balance
        self._daily_pnl      = 0.0
        self._trades_today   = []
        log.info(f"Saldo inicial do dia definido: ${balance:.2f}")

    # ── SL/TP dinâmico ───────────────────────────────────────

    def compute_sl_tp(self, entry_price: float, atr: float = None, side: str = "BUY") -> tuple:
        # Prioridade: executor runtime > adaptive > config
        if self._executor_ref:
            sl_pct = self._executor_ref._sl_pct
            tp_pct = self._executor_ref._tp_pct
        elif self.adaptive:
            sl_pct = self.adaptive.get_param("stop_loss_pct",   config.STOP_LOSS_PCT)
            tp_pct = self.adaptive.get_param("take_profit_pct", config.TAKE_PROFIT_PCT)
        else:
            sl_pct = config.STOP_LOSS_PCT
            tp_pct = config.TAKE_PROFIT_PCT

        if atr and atr > 0:
            sl = entry_price - (atr * config.SL_ATR_MULT)
            tp = entry_price + (atr * config.TP_ATR_MULT)
        else:
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)

        return round(sl, 8), round(tp, 8)

    def compute_position_size(self, balance: float, price: float,
                               atr: float = None) -> float:
        """Calcula quantidade respeitando o limite de USDT por ordem do executor."""
        if price <= 0:
            return 0.0

        # Limite em USDT — lê do executor se disponível
        if self._executor_ref:
            max_usdt = self._executor_ref._max_order_usdt
        else:
            max_usdt = getattr(config, "MAX_ORDER_USDT", 100.0)

        # Garante que não ultrapassa % do saldo
        max_usdt = min(max_usdt, balance * getattr(config, "POSITION_SIZE_PCT", 0.10))

        qty = round(max_usdt / price, 6)
        return max(qty, 0.000001)

    def check_trailing_stop(self, position: dict, current_price: float) -> bool:
        """FIX: usa lock para evitar condição de corrida em multi-par."""
        if not position:
            return False

        with self._lock:
            entry = position["entry_price"]
            high  = position.get("highest_price", entry)

            if current_price > high:
                position["highest_price"] = current_price
                high = current_price

        trail_pct = config.TRAILING_STOP_PCT
        trail_sl  = high * (1 - trail_pct)

        # Só dispara trailing se já está em lucro (> 0.5% acima da entrada)
        if current_price <= trail_sl and current_price < entry * 1.005:
            log.info(
                f"Trailing stop atingido: "
                f"${current_price:.2f} <= ${trail_sl:.2f}"
            )
            return True
        return False

    # ── Getters para GUI ──────────────────────────────────────

    def get_stats(self) -> dict:
        total = self._wins + self._losses
        wr    = (self._wins / total * 100) if total > 0 else 0.0
        return {
            "trades"      : total,
            "wins"        : self._wins,
            "losses"      : self._losses,
            "winrate"     : round(wr, 1),
            "total_pnl"   : round(self._total_pnl, 4),
            "daily_loss"  : round(self._daily_pnl,  4),
            "in_cooldown" : self._in_cooldown,
            "cooldown_rem": max(0, int(self._cooldown_until - time.time()))
        }