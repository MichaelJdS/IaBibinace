"""
ForexExecutor — executa ordens simuladas (DEMO) para pares forex.
Substitua os métodos _real_buy/_real_sell por chamadas OANDA
quando quiser ir para conta real.
"""
import time
import threading
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("ForexExecutor")


class ForexExecutor:
    def __init__(self):
        self._positions: dict = {}
        self._lock = threading.Lock()
        self._last_trade_id = None

    def get_balance(self, currency: str = "USD") -> float:
        return 1000.0  # demo fixo — substituir por query OANDA

    def get_open_position(self, symbol: str) -> dict | None:
        with self._lock:
            return self._positions.get(symbol)

    def get_open_positions(self) -> dict:
        with self._lock:
            return dict(self._positions)

    def buy(self, symbol: str, quantity: float, price: float,
            stop_loss: float, take_profit: float) -> bool:
        if config.TRADING_MODE == "REAL":
            return self._real_buy(symbol, quantity, price, stop_loss, take_profit)

        with self._lock:
            self._positions[symbol] = {
                "symbol": symbol,
                "side": "BUY",
                "entry_price": price,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": time.time(),
            }
        log.info(f"[DEMO] FOREX BUY {symbol} qty={quantity:.5f} @ {price:.5f} SL={stop_loss:.5f} TP={take_profit:.5f}")
        return True

    def sell(self, symbol: str, reason: str = "signal") -> tuple:
        pos = self.get_open_position(symbol)
        if not pos:
            return False, 0.0, 0.0, False

        if config.TRADING_MODE == "REAL":
            return self._real_sell(symbol, reason)

        entry = pos["entry_price"]
        current = self._get_current_price(symbol)
        qty = pos["quantity"]

        pnl_pct = (current - entry) / entry if pos["side"] == "BUY" else (entry - current) / entry
        pnl_usd = pnl_pct * entry * qty
        is_win = pnl_usd > 0

        with self._lock:
            self._positions.pop(symbol, None)

        log.info(f"[DEMO] FOREX SELL {symbol} @ {current:.5f} pnl={pnl_usd:.2f} ({reason})")
        return True, pnl_pct, pnl_usd, is_win

    def _get_current_price(self, symbol: str) -> float:
        # Injetado pelo brain via set_hub()
        if hasattr(self, "_hub") and self._hub:
            return self._hub.get_price(symbol)
        return 0.0

    def set_hub(self, hub):
        self._hub = hub

    def _real_buy(self, symbol, qty, price, sl, tp) -> bool:
        # TODO: implementar via OANDA REST API
        log.warning(f"REAL forex buy não implementado para {symbol}")
        return False

    def _real_sell(self, symbol, reason) -> tuple:
        log.warning(f"REAL forex sell não implementado para {symbol}")
        return False, 0.0, 0.0, False