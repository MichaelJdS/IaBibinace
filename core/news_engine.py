"""
NewsEngine v2 — usa Finnhub como fonte primária de notícias e sentimento.
Fallback para análise local se Finnhub indisponível.
"""
import time
import threading
import requests
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("NewsEngine")

SYMBOL_MAP = {
    "BTC":    "BINANCE:BTCUSDT",
    "ETH":    "BINANCE:ETHUSDT",
    "SOL":    "BINANCE:SOLUSDT",
    "BNB":    "BINANCE:BNBUSDT",
    "EURUSD": "OANDA:EUR_USD",
    "GBPUSD": "OANDA:GBP_USD",
    "USDJPY": "OANDA:USD_JPY",
    "XAUUSD": "OANDA:XAU_USD",
    "EUR":    "OANDA:EUR_USD",
    "GBP":    "OANDA:GBP_USD",
    "JPY":    "OANDA:USD_JPY",
    "XAU":    "OANDA:XAU_USD",
    "GOLD":   "OANDA:XAU_USD",
}

NEGATIVE_WORDS = {
    "crash", "dump", "ban", "hack", "bear", "loss", "decline",
    "fall", "fear", "sell", "drop", "collapse", "fraud", "risk",
    "warning", "lawsuit", "investigation", "exploit", "attack",
    "bankrupt", "insolvency", "regulatory", "fine", "penalty"
}

POSITIVE_WORDS = {
    "bull", "rally", "surge", "buy", "gain", "pump", "adoption",
    "partnership", "upgrade", "launch", "record", "high", "growth",
    "profit", "approval", "etf", "institutional", "integration",
    "breakout", "support", "accumulation", "invest", "expand"
}


class NewsEngine:
    def __init__(self):
        self._sentiments: dict[str, float] = {}
        self._headlines: dict[str, list] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._api_key = getattr(config, "FINNHUB_API_KEY", "")
        self._last_update: dict[str, float] = {}
        self._cache_ttl = 90  # segundos

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="NewsEngine"
        )
        self._thread.start()
        log.info("NewsEngine iniciado")

    def stop(self):
        self._running = False

    def _loop(self):
        symbols = list(set(
            s.replace("USDT", "").replace("USD", "")
            for s in getattr(config, "TRADING_PAIRS", ["BTCUSDT"])
        ))
        while self._running:
            for sym in symbols:
                try:
                    self._update_sentiment(sym)
                except Exception as e:
                    log.warning(f"NewsEngine erro {sym}: {e}")
                time.sleep(1.5)
            time.sleep(getattr(config, "NEWS_POLL_SEC", 120))

    def _update_sentiment(self, symbol: str):
        now = time.time()
        if now - self._last_update.get(symbol, 0) < self._cache_ttl:
            return

        if self._api_key:
            sentiment = self._fetch_finnhub_sentiment(symbol)
        else:
            sentiment = self._fetch_news_local(symbol)

        with self._lock:
            self._sentiments[symbol] = sentiment
            self._last_update[symbol] = now

        log.debug(f"Sentimento {symbol}: {sentiment:+.3f}")

    def _fetch_finnhub_sentiment(self, symbol: str) -> float:
        """Usa endpoint /news-sentiment do Finnhub (dados pro)
           + /company-news para análise léxica quando sentiment=0."""
        finnhub_sym = SYMBOL_MAP.get(symbol, symbol)

        # Tenta news-sentiment (só funciona para ações, não crypto)
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={finnhub_sym}&token={self._api_key}"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                score = data.get("companyNewsScore", 0)
                buzz  = data.get("buzz", {}).get("buzz", 1.0)
                if score != 0:
                    normalized = (score - 0.5) * 2  # 0..1 → -1..+1
                    return max(-1.0, min(1.0, normalized * min(buzz, 2.0)))
        except Exception:
            pass

        # Fallback: /news para crypto e forex — análise léxica
        return self._fetch_general_news_sentiment(symbol)

    def _fetch_general_news_sentiment(self, symbol: str) -> float:
        """Busca notícias gerais e calcula sentimento por léxico."""
        url = (
            f"https://finnhub.io/api/v1/news"
            f"?category=general&token={self._api_key}"
        )
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return 0.0
            articles = r.json()
        except Exception:
            return 0.0

        query = symbol.upper()
        relevant = [
            a for a in articles
            if query in (a.get("headline", "") + a.get("summary", "")).upper()
        ][:10]

        if not relevant:
            return 0.0

        pos = neg = 0
        for a in relevant:
            text = (a.get("headline", "") + " " + a.get("summary", "")).lower()
            pos += sum(1 for w in POSITIVE_WORDS if w in text)
            neg += sum(1 for w in NEGATIVE_WORDS if w in text)

        total = pos + neg
        if total == 0:
            return 0.0

        return max(-1.0, min(1.0, (pos - neg) / total))

    def _fetch_news_local(self, symbol: str) -> float:
        """Fallback quando não há chave Finnhub."""
        return 0.0

    def get_sentiment(self, symbol: str) -> float:
        clean = symbol.upper().replace("USDT", "").replace("USD", "")
        with self._lock:
            return self._sentiments.get(clean, self._sentiments.get(symbol, 0.0))

    def get_headlines(self, symbol: str) -> list:
        clean = symbol.upper().replace("USDT", "").replace("USD", "")
        with self._lock:
            return self._headlines.get(clean, [])