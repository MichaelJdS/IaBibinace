"""
Order Executor — Execução de ordens na Binance
Suporta: DEMO (demo-api.binance.com — conta demo oficial Binance)
         REAL (api.binance.com — conta real)

Não há mais simulação local: todas as ordens passam pela API Binance,
seja demo ou real. Os controles de risco (SL%, TP%, valor máximo por
ordem) podem ser ajustados em tempo real pela GUI via setters.
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
        self.mode       = config.TRADING_MODE          # "DEMO" | "REAL"
        self.api_key    = config.BINANCE_API_KEY
        self.api_secret = config.BINANCE_API_SECRET
        self.base_url   = config.BINANCE_ENDPOINTS[self.mode]["rest"]

        self._open_positions = {}
        self._lock           = threading.Lock()
        self._trade_history  = []
        self._last_trade_id  = None
        self._ws_ref         = None

        # ── Parâmetros de risco configuráveis em runtime ──────
        self._max_order_usdt = float(
            os.getenv("MAX_ORDER_USDT", getattr(config, "MAX_ORDER_USDT", 100.0))
        )
        self._sl_pct = config.STOP_LOSS_PCT    # ex: 0.015 = 1.5%
        self._tp_pct = config.TAKE_PROFIT_PCT  # ex: 0.025 = 2.5%

        log.info(
            f"OrderExecutor | modo={self.mode} | "
            f"url={self.base_url} | "
            f"max_order=${self._max_order_usdt:.2f} | "
            f"SL={self._sl_pct*100:.1f}% | TP={self._tp_pct*100:.1f}%"
        )

    # ── Setters chamados pela GUI em runtime ─────────────────

    def set_max_order_usdt(self, value: float):
        self._max_order_usdt = max(1.0, float(value))
        log.info(f"Max ordem atualizado: ${self._max_order_usdt:.2f}")

    def set_sl_pct(self, value: float):
        """value em decimal: 0.015 = 1.5%"""
        self._sl_pct = max(0.001, float(value))
        log.info(f"Stop Loss atualizado: {self._sl_pct*100:.2f}%")

    def set_tp_pct(self, value: float):
        """value em decimal: 0.025 = 2.5%"""
        self._tp_pct = max(0.001, float(value))
        log.info(f"Take Profit atualizado: {self._tp_pct*100:.2f}%")

    def get_risk_params(self) -> dict:
        return {
            "max_order_usdt": self._max_order_usdt,
            "sl_pct": self._sl_pct,
            "tp_pct": self._tp_pct,
        }

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

    # ── Referência ao WebSocket (para preço real) ─────────────

    def set_ws(self, ws):
        self._ws_ref = ws

    def _get_current_price(self, symbol: str) -> float:
        if self._ws_ref:
            try:
                return self._ws_ref.get_price(symbol)
            except Exception:
                pass
        # Fallback: busca direto na API
        try:
            r = requests.get(
                f"{self.base_url}/api/v3/ticker/price",
                params={"symbol": symbol}, timeout=5
            )
            if r.status_code == 200:
                return float(r.json().get("price", 0))
        except Exception:
            pass
        return 0.0

    # ── Propriedades de posição ───────────────────────────────

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
        try:
            r = requests.get(f"{self.base_url}/api/v3/ping", timeout=5)
            ok = r.status_code == 200
            log.info(f"Ping Binance {self.mode}: {'OK' if ok else 'FALHOU'}")
            return ok
        except Exception as e:
            log.error(f"Ping Binance falhou: {e}")
            return False

    # ── Saldo ─────────────────────────────────────────────────

    def get_balance(self, asset: str = "USDT") -> float:
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
            log.error(f"Erro ao buscar saldo {asset}: {e}")
        return 0.0

    def get_all_balances(self) -> dict:
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

    # ── Calcula quantidade baseada em USDT limite ─────────────

    def _calc_qty(self, price: float, usdt_limit: float = None) -> float:
        """Calcula quantidade em base asset a partir do valor em USDT."""
        limit = usdt_limit if usdt_limit else self._max_order_usdt
        if price <= 0:
            return 0.0
        return round(limit / price, 6)

    # ── BUY ───────────────────────────────────────────────────

    def buy(self, quantity: float = None, price: float = 0,
            symbol: str = None,
            stop_loss: float = None, take_profit: float = None,
            usdt_value: float = None) -> bool:
        """
        Executa ordem de compra na Binance (DEMO ou REAL).
        - Se `usdt_value` for passado, calcula qty automaticamente.
        - SL/TP usam os valores do executor se não informados.
        """
        symbol = symbol or config.PRIMARY_PAIR

        # Preço atual se não fornecido
        if price <= 0:
            price = self._get_current_price(symbol)
            if price <= 0:
                log.error(f"Não foi possível obter preço de {symbol}")
                return False

        # Quantidade: prioridade usdt_value > quantity > _max_order_usdt
        if usdt_value and usdt_value > 0:
            quantity = self._calc_qty(price, usdt_value)
        elif not quantity or quantity <= 0:
            quantity = self._calc_qty(price, self._max_order_usdt)

        # SL/TP com os parâmetros do executor
        sl = stop_loss   if stop_loss   is not None else price * (1 - self._sl_pct)
        tp = take_profit if take_profit is not None else price * (1 + self._tp_pct)

        with self._lock:
            if symbol in self._open_positions:
                log.warning(f"Já existe posição aberta para {symbol}. Ignorando BUY.")
                return False

        # Valida notional mínimo
        min_notional = getattr(config, "MIN_NOTIONAL", 10.0)
        if quantity * price < min_notional:
            log.warning(
                f"Ordem abaixo do notional mínimo: "
                f"${quantity * price:.2f} < ${min_notional} — ajustando"
            )
            quantity = round(min_notional / price * 1.05, 6)

        try:
            ts     = int(time.time() * 1000)
            params = {
                "symbol"   : symbol,
                "side"     : "BUY",
                "type"     : "MARKET",
                "quantity" : f"{quantity:.6f}",
                "timestamp": ts
            }
            params["signature"] = self._sign(params)
            r = requests.post(
                f"{self.base_url}/api/v3/order",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            order      = r.json()
            fills      = order.get("fills", [])
            fill_price = float(fills[0].get("price", price)) if fills else price

            with self._lock:
                self._open_positions[symbol] = {
                    "symbol"       : symbol,
                    "side"         : "BUY",
                    "quantity"     : quantity,
                    "entry_price"  : fill_price,
                    "stop_loss"    : round(sl, 8),
                    "take_profit"  : round(tp, 8),
                    "entry_time"   : time.time(),
                    "highest_price": fill_price,
                    "order_id"     : order.get("orderId"),
                    "usdt_value"   : round(quantity * fill_price, 4),
                }
            log.info(
                f"✅ BUY {self.mode} | {quantity:.6f} {symbol} @ "
                f"${fill_price:,.4f} | "
                f"SL=${sl:,.4f} TP=${tp:,.4f} | "
                f"Valor=${quantity * fill_price:,.2f}"
            )
            return True

        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.json()
            except Exception:
                pass
            log.error(f"Erro HTTP BUY {symbol}: {e} | {body}")
            return False
        except Exception as e:
            log.error(f"Erro ao executar BUY: {e}")
            return False

    # ── SELL ──────────────────────────────────────────────────

    def sell(self, symbol: str = None, reason: str = "signal") -> tuple:
        """
        Retorna sempre tupla (ok: bool, pnl_pct, pnl_usd, is_win).
        """
        with self._lock:
            pos = self._open_positions.get(symbol) if symbol else \
                  next(iter(self._open_positions.values()), None)

        if not pos:
            log.warning("Nenhuma posição aberta para SELL.")
            return False, 0.0, 0.0, False

        symbol     = pos["symbol"]
        quantity   = pos["quantity"]
        entry      = pos["entry_price"]
        entry_time = pos.get("entry_time", time.time())

        try:
            ts     = int(time.time() * 1000)
            params = {
                "symbol"   : symbol,
                "side"     : "SELL",
                "type"     : "MARKET",
                "quantity" : f"{quantity:.6f}",
                "timestamp": ts
            }
            params["signature"] = self._sign(params)
            r = requests.post(
                f"{self.base_url}/api/v3/order",
                params=params, headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            order      = r.json()
            fills      = order.get("fills", [])
            exit_price = float(fills[0].get("price", entry)) if fills else entry

            pnl_usd  = (exit_price - entry) * quantity
            pnl_pct  = (exit_price - entry) / entry * 100
            is_win   = pnl_usd > 0
            duration = round(time.time() - entry_time, 0)

            record = {
                "symbol"  : symbol,
                "entry"   : entry,
                "exit"    : exit_price,
                "qty"     : quantity,
                "pnl_usd" : round(pnl_usd, 4),
                "pnl_pct" : round(pnl_pct,  2),
                "reason"  : reason,
                "duration": duration
            }
            self._trade_history.append(record)

            with self._lock:
                del self._open_positions[symbol]

            log.info(
                f"{'✅' if is_win else '❌'} SELL {self.mode} | "
                f"{quantity:.6f} {symbol} @ ${exit_price:,.4f} | "
                f"PnL: ${pnl_usd:+.4f} ({pnl_pct:+.2f}%) | "
                f"Razão: {reason}"
            )
            return True, pnl_pct / 100, pnl_usd, is_win

        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.json()
            except Exception:
                pass
            log.error(f"Erro HTTP SELL {symbol}: {e} | {body}")
            return False, 0.0, 0.0, False
        except Exception as e:
            log.error(f"Erro ao executar SELL: {e}")
            return False, 0.0, 0.0, False

    def get_trade_history(self) -> list:
        return self._trade_history.copy()