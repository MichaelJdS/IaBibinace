"""
Binance WebSocket Manager — Streams de preço, candles e book
Thread-safe, reconexão automática, buffer de ticks e candles
"""
import json
import time
import threading
import queue
import websocket
import requests
import pandas as pd
from collections import deque
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("BinanceWS")


class TickState:
    """Estado de mercado por símbolo."""
    def __init__(self, symbol: str):
        self.symbol    = symbol
        self.price     = 0.0
        self.bid       = 0.0
        self.ask       = 0.0
        self.spread    = 0.0
        self.vwap      = 0.0
        self._ticks    = deque(maxlen=500)
        self._lock     = threading.Lock()

    def update_price(self, price: float, qty: float = 0):
        with self._lock:
            self.price = price
            self._ticks.append({
                "ts"    : time.time(),
                "price" : price,
                "qty"   : qty
            })
            # VWAP incremental
            if qty > 0:
                pv = sum(t["price"] * t["qty"] for t in self._ticks if t["qty"] > 0)
                v  = sum(t["qty"] for t in self._ticks if t["qty"] > 0)
                self.vwap = pv / v if v > 0 else price

    def update_book(self, bid: float, ask: float):
        with self._lock:
            self.bid    = bid
            self.ask    = ask
            self.spread = round(ask - bid, 4)

    def get_ticks_df(self) -> pd.DataFrame:
        with self._lock:
            ticks = list(self._ticks)
        if not ticks:
            return pd.DataFrame()
        return pd.DataFrame(ticks)


class CandleBuffer:
    """Buffer de candles OHLCV por timeframe."""
    def __init__(self, maxlen: int = 500):
        self._candles  = deque(maxlen=maxlen)
        self._open_bar = None
        self._lock     = threading.Lock()

    def update(self, kline: dict):
        with self._lock:
            bar = {
                "open"     : float(kline["o"]),
                "high"     : float(kline["h"]),
                "low"      : float(kline["l"]),
                "close"    : float(kline["c"]),
                "volume"   : float(kline["v"]),
                "ts"       : int(kline["t"]) // 1000,
                "closed"   : kline.get("x", False)
            }
            if bar["closed"]:
                if self._open_bar:
                    self._candles.append(self._open_bar)
                self._open_bar = bar
            else:
                self._open_bar = bar

    def to_dataframe(self) -> pd.DataFrame:
        with self._lock:
            candles = list(self._candles)
            if self._open_bar:
                candles.append(self._open_bar)
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        df.set_index("ts", inplace=True)
        df.index = pd.to_datetime(df.index, unit="s")
        return df[["open","high","low","close","volume"]].copy()

    def __len__(self):
        with self._lock:
            return len(self._candles)


class BinanceWebSocketManager:
    def __init__(self):
        self._tick_states    = {}
        self._candle_buffers = {}
        self._connections    = {}
        self._running        = False
        self._reconnect_delay= 5
        self._lock           = threading.Lock()
        self._init_structures()
        log.info("BinanceWebSocketManager criado")

    def _init_structures(self):
        for pair in config.TRADING_PAIRS:
            sym = pair.lower()
            self._tick_states[pair]    = TickState(pair)
            self._candle_buffers[pair] = {
                tf: CandleBuffer() for tf in [
                    config.TF_PRIMARY, config.TF_FAST, config.TF_SLOW
                ]
            }

    # ── Inicialização ─────────────────────────────────────────

    def start(self):
        self._running = True
        for pair in config.TRADING_PAIRS:
            self._load_historical(pair)
        self._start_streams()
        log.info("WebSocket streams iniciados")

    def stop(self):
        self._running = False
        for ws in self._connections.values():
            try:
                ws.close()
            except Exception:
                pass
        log.info("WebSocket streams encerrados")

    # ── Candles históricos (REST) ─────────────────────────────

    def _load_historical(self, pair: str):
        for tf in [config.TF_PRIMARY, config.TF_FAST, config.TF_SLOW]:
            try:
                endpoint = config.BINANCE_ENDPOINTS[config.TRADING_MODE]
                # Demo usa endpoint live para dados históricos
                rest_url = endpoint.get("rest", "https://api.binance.com")
                url      = f"{rest_url}/api/v3/klines"
                params   = {
                    "symbol"  : pair,
                    "interval": tf,
                    "limit"   : 300
                }
                r = requests.get(url, params=params, timeout=15)
                r.raise_for_status()
                klines = r.json()

                buf = self._candle_buffers[pair][tf]
                for k in klines:
                    bar = {
                        "o": k[1], "h": k[2], "l": k[3],
                        "c": k[4], "v": k[5], "t": k[0], "x": True
                    }
                    buf.update(bar)
                log.info(f"Histórico carregado: {pair} {tf} → {len(buf)} candles")
            except Exception as e:
                log.warning(f"Erro histórico {pair} {tf}: {e}")

    # ── Streams WebSocket ─────────────────────────────────────

    def _start_streams(self):
        for pair in config.TRADING_PAIRS:
            t = threading.Thread(
                target=self._connect_pair,
                args=(pair,),
                daemon=True,
                name=f"WS-{pair}"
            )
            t.start()

    def _connect_pair(self, pair: str):
        sym = pair.lower()
        tfs = [config.TF_PRIMARY, config.TF_FAST, config.TF_SLOW]

        streams = [f"{sym}@aggTrade"]
        streams += [f"{sym}@kline_{tf}" for tf in tfs]
        streams += [f"{sym}@bookTicker"]

        endpoint  = config.BINANCE_ENDPOINTS[config.TRADING_MODE]
        ws_base   = endpoint.get("ws_stream", "wss://stream.binance.com:9443/ws")
        stream_url= f"{ws_base}/{'/'.join(streams)}"

        while self._running:
            try:
                log.debug(f"Conectando WS: {pair}")
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_message=lambda w, m: self._on_message(pair, m),
                    on_error  =lambda w, e: log.warning(f"WS {pair} erro: {e}"),
                    on_close  =lambda w, c, m: log.debug(f"WS {pair} fechado")
                )
                with self._lock:
                    self._connections[pair] = ws
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.error(f"WS {pair} falhou: {e}")

            if self._running:
                log.info(f"Reconectando {pair} em {self._reconnect_delay}s...")
                time.sleep(self._reconnect_delay)

    def _on_message(self, pair: str, raw: str):
        try:
            msg    = json.loads(raw)
            stream = msg.get("stream", "")
            data   = msg.get("data", msg)
            e_type = data.get("e", "")

            # Tick de preço
            if e_type == "aggTrade":
                price = float(data["p"])
                qty   = float(data["q"])
                self._tick_states[pair].update_price(price, qty)

            # Candle
            elif e_type == "kline":
                kline = data["k"]
                tf    = kline.get("i")
                if tf and tf in self._candle_buffers.get(pair, {}):
                    self._candle_buffers[pair][tf].update(kline)

            # Book ticker
            elif e_type == "bookTicker" or "b" in data and "a" in data:
                bid = float(data.get("b", 0))
                ask = float(data.get("a", 0))
                if bid > 0 and ask > 0:
                    self._tick_states[pair].update_book(bid, ask)

        except Exception as e:
            log.debug(f"Erro parse WS {pair}: {e}")

    # ── Getters públicos ─────────────────────────────────────

    def get_price(self, pair: str) -> float:
        return self._tick_states.get(pair, TickState(pair)).price

    def get_state(self, pair: str) -> TickState:
        return self._tick_states.get(pair)

    def get_vwap(self, pair: str) -> float:
        state = self._tick_states.get(pair)
        return state.vwap if state else 0.0

    def get_candles(self, pair: str, tf: str = None) -> pd.DataFrame:
        tf = tf or config.TF_PRIMARY
        buf = self._candle_buffers.get(pair, {}).get(tf)
        if buf:
            return buf.to_dataframe()
        return pd.DataFrame()

    def get_spread(self, pair: str) -> float:
        state = self._tick_states.get(pair)
        return state.spread if state else 0.0

    def is_connected(self, pair: str) -> bool:
        return pair in self._connections