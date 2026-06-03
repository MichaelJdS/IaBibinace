"""
MarketDataHub — centraliza dados de mercado para cripto e forex.
- Cripto: BinanceWebSocketManager (já existente)
- Forex: yfinance em polling (substituível por OANDA)
"""
import time
import threading
import pandas as pd
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("MarketDataHub")

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    log.warning("yfinance não instalado. Forex indisponível.")

YFINANCE_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",
}

TF_MAP_YFINANCE = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "1h":  "1h",
}

class ForexFeed:
    """Polling de candles forex via yfinance."""

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._prices: dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._poll_interval = 30

    def start(self):
        if not YFINANCE_AVAILABLE:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ForexFeed")
        self._thread.start()
        log.info("ForexFeed iniciado")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for pair in config.FOREX_PAIRS:
                try:
                    self._update(pair)
                except Exception as e:
                    log.warning(f"ForexFeed erro {pair}: {e}")
            time.sleep(self._poll_interval)

    def _update(self, pair: str):
        yfsym = YFINANCE_SYMBOL_MAP.get(pair)
        if not yfsym:          # ← era "yfym", corrigido para "yfsym"
            return
        ticker = yf.Ticker(yfsym)   # ← era "yfym", corrigido para "yfsym"
        df = ticker.history(period="1d", interval="1m")
        if df.empty:
            return
        df = df.rename(columns={
            "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume"
        })
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        with self._lock:
            self._cache[pair] = df
            self._prices[pair] = float(df["close"].iloc[-1])

    def get_price(self, pair: str) -> float:
        with self._lock:
            return self._prices.get(pair, 0.0)

    def get_candles(self, pair: str, tf: str = "1m") -> pd.DataFrame:
        with self._lock:
            return self._cache.get(pair, pd.DataFrame()).copy()


class MarketDataHub:
    """
    Ponto único de acesso a dados — roteia crypto para BinanceWS
    e forex para ForexFeed automaticamente.
    """

    def __init__(self, binance_ws):
        self.binance_ws = binance_ws
        self.forex_feed = ForexFeed()

    def start(self):
        self.binance_ws.start()
        if YFINANCE_AVAILABLE:
            for pair in config.FOREX_PAIRS:
                try:
                    self.forex_feed._update(pair)
                except Exception as e:
                    log.warning(f"ForexFeed init {pair}: {e}")
        self.forex_feed.start()
        log.info("MarketDataHub iniciado")

    def stop(self):
        self.binance_ws.stop()
        self.forex_feed.stop()

    def get_price(self, symbol: str) -> float:
        if config.MARKET_TYPE_MAP.get(symbol) == "forex":
            return self.forex_feed.get_price(symbol)
        return self.binance_ws.get_price(symbol)

    def get_candles(self, symbol: str, tf: str = "1m") -> pd.DataFrame:
        if config.MARKET_TYPE_MAP.get(symbol) == "forex":
            return self.forex_feed.get_candles(symbol, tf)
        return self.binance_ws.get_candles(symbol, tf)

    def is_ready(self, symbol: str) -> bool:
        price = self.get_price(symbol)
        return price > 0