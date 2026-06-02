"""
Risk Engine — Gerenciamento de risco completo
SL/TP/Trailing, cooldown, limites diários, drawdown
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
        self.db             = db_engine
        self.adaptive       = adaptive_engine
        self._lock          = threading.Lock()
        self.daily_start_bal= 1000.0
        self._trades_today  = []
        self._wins          = 0
        self._losses        = 0
        self._total_pnl     = 0.0
        self._daily_pnl     = 0.0
        self._in_cooldown   = False
        self._cooldown_until= 0
        self._open_trade_id = None
        self._session_start = int(time.time())
        log.info("RiskEngine iniciado")

    # ── Verificações de entrada ───────────────────────────────

    def can_trade(self, open_positions: int = 0) -> tuple[bool, str]:
        """Retorna (pode_operar, motivo_bloqueio)."""

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
                     is_win: bool, reason: str, trade_id: int = None):
        with self._lock:
            self._total_pnl  += pnl_usd
            self._daily_pnl  += pnl_usd

            if is_win:
                self._wins += 1
            else:
                self._losses += 1
                # Ativa cooldown em perda
                cd = self.adaptive.get_param("cooldown_seconds") if self.adaptive \
                     else config.COOLDOWN_SECONDS
                self._in_cooldown   = True
                self._cooldown_until= time.time() + cd
                log.warning(f"SL atingido → Cooldown {cd}s | PnL: ${pnl_usd:.4f}")

            self._trades_today.append({
                "time"    : int(time.time()),
                "pnl_usd" : pnl_usd,
                "pnl_pct" : pnl_pct,
                "win"     : is_win,
                "reason"  : reason
            })

        # Salva no banco
        if self.db and trade_id:
            self.db.save_trade_close(trade_id, {
                "pnl_usd"    : pnl_usd,
                "pnl_pct"    : pnl_pct,
                "reason"     : reason,
                "duration_sec": 0,
                "exit_price" : 0
            })

        # Dispara avaliação adaptativa
        if self.adaptive:
            self.adaptive.evaluate()
            self.adaptive.apply_to_runtime()

    def set_daily_start_balance(self, balance: float):
        self.daily_start_bal = balance
        self._daily_pnl      = 0.0
        self._trades_today   = []
        log.info(f"Saldo inicial do dia definido: ${balance:.2f}")

    # ── SL/TP dinâmico ───────────────────────────────────────

    def compute_sl_tp(self, entry_price: float, atr: float = None) -> tuple:
        """Retorna (stop_loss, take_profit) com base em ATR ou % config."""
        if self.adaptive:
            sl_pct = self.adaptive.get_param("stop_loss_pct",  config.STOP_LOSS_PCT)
            tp_pct = self.adaptive.get_param("take_profit_pct", config.TAKE_PROFIT_PCT)
        else:
            sl_pct = config.STOP_LOSS_PCT
            tp_pct = config.TAKE_PROFIT_PCT

        # Se ATR disponível → usa 2× ATR para SL, 3× para TP
        if atr and atr > 0:
            sl = entry_price - (atr * 2.0)
            tp = entry_price + (atr * 3.0)
        else:
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)

        return round(sl, 2), round(tp, 2)

    def compute_position_size(self, balance: float, price: float,
                               atr: float = None) -> float:
        """Kelly-inspired sizing com teto de risco."""
        base_qty = config.TRADE_QUANTITY
        if self.adaptive:
            size_pct = self.adaptive.get_param("position_size_pct", 0.8)
        else:
            size_pct = 0.8

        # Nunca arriscar mais de 2% do saldo em uma entrada
        max_risk_usd = balance * 0.02
        sl_pct       = self.adaptive.get_param("stop_loss_pct", config.STOP_LOSS_PCT) \
                       if self.adaptive else config.STOP_LOSS_PCT
        risk_per_unit= price * sl_pct
        if risk_per_unit > 0:
            max_qty_by_risk = max_risk_usd / risk_per_unit
            qty = min(base_qty * size_pct, max_qty_by_risk)
        else:
            qty = base_qty * size_pct

        return round(max(qty, 0.0001), 6)

    def check_trailing_stop(self, position: dict, current_price: float) -> bool:
        """Retorna True se trailing stop foi atingido."""
        if not position:
            return False
        entry  = position["entry_price"]
        high   = position.get("highest_price", entry)

        # Atualiza máximo
        if current_price > high:
            position["highest_price"] = current_price
            high = current_price

        trail_pct = config.TRAILING_STOP_PCT
        trail_sl  = high * (1 - trail_pct)

        if current_price <= trail_sl and current_price < entry * 1.005:
            log.info(f"Trailing stop atingido: ${current_price:.2f} <= ${trail_sl:.2f}")
            return True
        return False

    # ── Getters para GUI ──────────────────────────────────────

    def get_stats(self) -> dict:
        total  = self._wins + self._losses
        wr     = (self._wins / total * 100) if total > 0 else 0
        return {
            "trades"      : total,
            "wins"        : self._wins,
            "losses"      : self._losses,
            "winrate"     : round(wr, 1),
            "total_pnl"   : round(self._total_pnl, 4),
            "daily_loss"  : round(self._daily_pnl, 4),
            "in_cooldown" : self._in_cooldown,
            "cooldown_rem": max(0, int(self._cooldown_until - time.time()))
        }