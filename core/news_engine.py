"""
News Engine — Finnhub news + sentimento com cache
"""
import time
import threading
import requests
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("NewsEngine")

CRYPTO_MAP = {
    "BTC": "BINANCE:BTCUSDT",
    "ETH": "BINANCE:ETHUSDT",
    "BNB": "BINANCE:BNBUSDT",
}

class NewsEngine:
    def __init__(self):
        self._lock       = threading.Lock()
        self._news_cache = {}      # symbol → [news]
        self._sentiment  = {       # symbol → float (-1..+1)
            "BTC": 0.0, "ETH": 0.0, "BNB": 0.0, "GLOBAL": 0.0
        }
        self._event_risk = "low"
        self._last_fetch = {}
        self._fetch_interval = 180  # 3 min
        self._running    = False
        self._thread     = None
        log.info("NewsEngine iniciado")

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="NewsEngine"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for sym in ["BTC", "ETH", "BNB"]:
                self._fetch_news(sym)
            self._fetch_global_news()
            time.sleep(self._fetch_interval)

    def _fetch_news(self, symbol: str):
        now  = int(time.time())
        last = self._last_fetch.get(symbol, 0)
        if now - last < self._fetch_interval:
            return

        try:
            url    = "https://finnhub.io/api/v1/news"
            params = {
                "category": "crypto",
                "token"   : config.FINNHUB_API_KEY
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            news = r.json()

            # Filtra por símbolo
            kw   = symbol.lower()
            filtered = [
                n for n in news
                if kw in n.get("headline", "").lower()
                or kw in n.get("summary",  "").lower()
            ][:30]

            with self._lock:
                self._news_cache[symbol] = filtered
                self._sentiment[symbol]  = self._calc_sentiment(filtered)
                self._last_fetch[symbol] = now

            log.debug(f"News {symbol}: {len(filtered)} artigos | sent={self._sentiment[symbol]:.2f}")
        except Exception as e:
            log.warning(f"Erro ao buscar news {symbol}: {e}")

    def _fetch_global_news(self):
        try:
            url    = "https://finnhub.io/api/v1/news"
            params = {"category": "general", "token": config.FINNHUB_API_KEY}
            r      = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            news   = r.json()[:20]

            global_sent = self._calc_sentiment(news)
            risk        = self._assess_event_risk(news)

            with self._lock:
                self._news_cache["GLOBAL"] = news
                self._sentiment["GLOBAL"]  = global_sent
                self._event_risk           = risk

        except Exception as e:
            log.debug(f"Erro global news: {e}")

    def _calc_sentiment(self, news: list) -> float:
        if not news:
            return 0.0

        positive = ["bullish","rally","surge","jump","gains","recovery",
                    "breakout","all-time","ath","adopt","partnership",
                    "buy","upgrade","record","approve","approved","etf"]
        negative = ["bearish","crash","drop","decline","sell","plunge",
                    "hack","ban","fraud","risk","warning","fear","fud",
                    "regulation","sec","lawsuit","exploit","lose"]

        scores = []
        for n in news:
            text  = (n.get("headline","") + " " + n.get("summary","")).lower()
            pos   = sum(1 for w in positive if w in text)
            neg   = sum(1 for w in negative if w in text)
            total = pos + neg
            if total > 0:
                scores.append((pos - neg) / total)

        return round(sum(scores) / len(scores), 3) if scores else 0.0

    def _assess_event_risk(self, news: list) -> str:
        high_risk_kw = [
            "fed","federal reserve","interest rate","cpi","inflation",
            "war","crisis","ban","emergency","hack","exploit",
            "sanctions","recession"
        ]
        count = 0
        for n in news:
            text = (n.get("headline","") + n.get("summary","")).lower()
            count += sum(1 for kw in high_risk_kw if kw in text)

        if count >= 5:
            return "high"
        elif count >= 2:
            return "medium"
        return "low"

    # ── Getters ───────────────────────────────────────────────

    def get_sentiment(self, symbol: str) -> float:
        with self._lock:
            return self._sentiment.get(symbol, 0.0)

    def get_event_risk(self) -> str:
        with self._lock:
            return self._event_risk

    def get_news_feed(self, limit: int = 20) -> list:
        with self._lock:
            all_news = []
            for news in self._news_cache.values():
                all_news.extend(news)
        all_news.sort(key=lambda x: x.get("datetime", 0), reverse=True)
        return all_news[:limit]

    def get_combined_sentiment(self) -> float:
        """Média ponderada de todos os sentimentos."""
        with self._lock:
            btc = self._sentiment["BTC"]   * 0.5
            eth = self._sentiment["ETH"]   * 0.25
            bnb = self._sentiment["BNB"]   * 0.1
            gl  = self._sentiment["GLOBAL"]* 0.15
        return round(btc + eth + bnb + gl, 3)