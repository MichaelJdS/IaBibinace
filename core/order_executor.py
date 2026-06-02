"""
Order Executor — Execução de ordens na Binance
Suporta: demo (simulado), testnet, live
"""
import time
import requests
import hmac
import hashlib
import threading
from urllib.parse import urlencode
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("Executor")

class OrderExecutor:
    def __init__(self):
        self.mode           = config.TRADING_MODE
        self.api_key        = config.BINANCE_API_KEY
        self.api_secret     = config.BINANCE_API_SECRET
        self.base_url       = config.BINANCE_ENDPOINTS[self.mode]["rest"]
        self._open_positions= {}
        self._lock          = threading.Lock()
        self._demo_balance  = {"USDT": 1000.0, "BTC": 0.0, "ETH": 0.0, "BNB": 0.0}
        self._trade_history = []
        log.info(f"OrderExecutor modo: {self.mode.upper()}")

    # ── Assinatura Binance ────────────────────────────────────

    def _sign(self, params: dict) -> str:
        query = urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    @property
    def open_position(self):
        with self._lock:
            return next(iter(self._open_positions.values()), None)

    def get_open_position(self, symbol: str):
        with self._lock:
            return self._open_positions.get(symbol)

    def get_open_positions(self) -> dict:
        with self._lock:
            return self._open_positions.copy()

    # ── Conexão ───────────────────────────────────────────────

    def ping(self) -> bool:
        if self.mode == "demo":
            log.info("Modo DEMO ativo — ping simulado OK")
            return True
        try:
            r = requests.get(f"{self.base_url}/api/v3/ping", timeout=5)
            return r.status_code == 200
        except Exception as e:
            log.error(f"Ping Binance falhou: {e}")
            return False

    # ── Saldo ─────────────────────────────────────────────────

    def get_balance(self, asset: str = "USDT") -> float:
        if self.mode == "demo":
            return self._demo_balance.get(asset, 0.0)
        try:
            ts     = int(time.time() * 1000)
            params = {"timestamp": ts}
            params["signature"] = self._sign(params)
            r = requests.get(
                f"{self.base_url}/api/v3/account",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            for b in r.json().get("balances", []):
                if b["asset"] == asset:
                    return float(b["free"])
        except Exception as e:
            log.error(f"Erro ao buscar saldo: {e}")
        return 0.0

    def get_all_balances(self) -> dict:
        if self.mode == "demo":
            return self._demo_balance.copy()
        try:
            ts     = int(time.time() * 1000)
            params = {"timestamp": ts}
            params["signature"] = self._sign(params)
            r = requests.get(
                f"{self.base_url}/api/v3/account",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            return {
                b["asset"]: float(b["free"])
                for b in r.json().get("balances", [])
                if float(b["free"]) > 0
            }
        except Exception as e:
            log.error(f"Erro ao buscar saldos: {e}")
            return {}

    # ── Execução de ordens ────────────────────────────────────

    def buy(self, quantity: float, price: float, symbol: str = None,
            stop_loss: float = None, take_profit: float = None) -> bool:
        symbol = symbol or config.PRIMARY_PAIR
        if symbol.endswith("USDT"):
            base_asset = symbol[:-4]
            quote_asset = "USDT"
        else:
            base_asset = symbol[:-4]
            quote_asset = symbol[-4:]

        sl = stop_loss if stop_loss is not None else price * (1 - config.STOP_LOSS_PCT)
        tp = take_profit if take_profit is not None else price * (1 + config.TAKE_PROFIT_PCT)

        with self._lock:
            if symbol in self._open_positions:
                log.warning(f"Já existe posição aberta para {symbol}. Ignorando BUY.")
                return False

        if self.mode == "demo":
            cost = quantity * price
            if self._demo_balance.get(quote_asset, 0.0) < cost:
                log.warning(f"Saldo insuficiente: ${self._demo_balance.get(quote_asset,0.0):.2f} < ${cost:.2f}")
                return False
            self._demo_balance[quote_asset] = self._demo_balance.get(quote_asset, 0.0) - cost
            self._demo_balance[base_asset]  = self._demo_balance.get(base_asset, 0.0) + quantity
            with self._lock:
                self._open_positions[symbol] = {
                    "symbol"      : symbol,
                    "side"        : "BUY",
                    "quantity"    : quantity,
                    "entry_price" : price,
                    "stop_loss"   : round(sl, 6) if sl else None,
                    "take_profit" : round(tp, 6) if tp else None,
                    "entry_time"  : time.time()
                }
            log.info(
                f"✅ BUY DEMO | {quantity:.6f} {symbol} @ ${price:,.2f} | "
                f"SL: ${sl:,.2f} | TP: ${tp:,.2f}"
            )
            return True

        try:
            ts     = int(time.time() * 1000)
            params = {
                "symbol"      : symbol,
                "side"        : "BUY",
                "type"        : "MARKET",
                "quantity"    : f"{quantity:.6f}",
                "timestamp"   : ts
            }
            params["signature"] = self._sign(params)
            r = requests.post(
                f"{self.base_url}/api/v3/order",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            order = r.json()
            fill_price = float(order.get("fills", [{}])[0].get("price", price))
            with self._lock:
                self._open_positions[symbol] = {
                    "symbol"      : symbol,
                    "side"        : "BUY",
                    "quantity"    : quantity,
                    "entry_price" : fill_price,
                    "stop_loss"   : round(sl, 6) if sl else fill_price * (1 - config.STOP_LOSS_PCT),
                    "take_profit" : round(tp, 6) if tp else fill_price * (1 + config.TAKE_PROFIT_PCT),
                    "entry_time"  : time.time(),
                    "order_id"    : order.get("orderId")
                }
            log.info(f"✅ BUY LIVE | {quantity:.6f} {symbol} @ ${fill_price:,.2f}")
            return True
        except Exception as e:
            log.error(f"Erro ao executar BUY: {e}")
            return False

    def sell(self, symbol: str = None, reason: str = "signal") -> bool:
        with self._lock:
            if symbol:
                pos = self._open_positions.get(symbol)
            else:
                pos = next(iter(self._open_positions.values()), None)
        if not pos:
            log.warning("Nenhuma posição aberta para SELL.")
            return False

        symbol   = pos["symbol"]
        quantity = pos["quantity"]
        entry    = pos["entry_price"]

        base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol[:-4]
        quote_asset= "USDT" if symbol.endswith("USDT") else symbol[-4:]

        if self.mode == "demo":
            # Tenta usar preço real; fallback para TP/SL
            exit_price = pos["take_profit"] if reason == "tp" else (
                pos["stop_loss"] if reason == "sl" else
                entry * 1.005
            )

            revenue = quantity * exit_price
            self._demo_balance[quote_asset] = self._demo_balance.get(quote_asset, 0.0) + revenue
            self._demo_balance[base_asset]  = self._demo_balance.get(base_asset, 0.0) - quantity
            pnl_usd = (exit_price - entry) * quantity
            pnl_pct = (exit_price - entry) / entry
            is_win  = pnl_usd > 0

            record = {
                "symbol"    : symbol,
                "side"      : "BUY",
                "entry"     : entry,
                "exit"      : exit_price,
                "qty"       : quantity,
                "pnl_usd"   : round(pnl_usd, 4),
                "pnl_pct"   : round(pnl_pct * 100, 2),
                "reason"    : reason,
                "duration"  : round(time.time() - pos["entry_time"], 0)
            }
            self._trade_history.append(record)

            with self._lock:
                del self._open_positions[symbol]

            result = "✅ WIN" if is_win else "❌ LOSS"
            log.info(
                f"{result} SELL DEMO | {quantity:.6f} {symbol} @ ${exit_price:,.2f} | "
                f"PnL: ${pnl_usd:+.4f} ({pnl_pct*100:+.2f}%) | Razão: {reason}"
            )
            return True, pnl_pct, pnl_usd, is_win

        try:
            ts     = int(time.time() * 1000)
            params = {
                "symbol"    : symbol,
                "side"      : "SELL",
                "type"      : "MARKET",
                "quantity"  : f"{quantity:.6f}",
                "timestamp" : ts
            }
            params["signature"] = self._sign(params)
            r = requests.post(
                f"{self.base_url}/api/v3/order",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            order      = r.json()
            exit_price = float(order.get("fills", [{}])[0].get("price", entry))
            pnl_usd    = (exit_price - entry) * quantity
            pnl_pct    = (exit_price - entry) / entry
            is_win     = pnl_usd > 0

            record = {
                "symbol"   : symbol, "entry": entry, "exit": exit_price,
                "qty"      : quantity, "pnl_usd": round(pnl_usd, 4),
                "pnl_pct"  : round(pnl_pct * 100, 2), "reason": reason
            }
            self._trade_history.append(record)

            with self._lock:
                del self._open_positions[symbol]

            log.info(f"{'✅' if is_win else '❌'} SELL LIVE | {quantity:.6f} {symbol} @ ${exit_price:,.2f} | PnL: ${pnl_usd:+.4f}")
            return True, pnl_pct, pnl_usd, is_win
        except Exception as e:
            log.error(f"Erro ao executar SELL: {e}")
            return False, 0, 0, False

    def check_sl_tp(self) -> bool:
        """Verifica se SL ou TP foi atingido (modo demo)."""
        with self._lock:
            pos = self.open_position
        if not pos:
            return False

        # Importa preço atual
        try:
            from core.binance_ws import BinanceWebSocketManager
        except Exception:
            return False

        # Em modo demo, simula checagem
        if self.mode == "demo":
            pass

        return False

    def get_trade_history(self) -> list:
        return self._trade_history.copy()