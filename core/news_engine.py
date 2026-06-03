"""
NewsEngine v3 — usa Finnhub como fonte primária de notícias e sentimento.
FIXES v3:
  - Warm-up imediato ao start() (thread separada)
  - Sentimento GLOBAL calculado como média de todos os pares
  - force_refresh() para botão manual na GUI
  - Cache reduzido para 120s
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
        self._headlines:  dict[str, list]  = {}
        self._lock     = threading.Lock()
        self._running  = False
        self._thread   = None
        self._api_key  = getattr(config, "FINNHUB_API_KEY", "")
        self._last_update: dict[str, float] = {}
        self._cache_ttl   = 120          # 2 minutos
        self._news_cache: list = []
        self._news_cache_ts: float = 0
        self._last_refresh_ts: float = 0

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="NewsEngine"
        )
        self._thread.start()

        # Warm-up: busca notícias e sentimentos imediatamente em thread separada
        threading.Thread(target=self._warmup, daemon=True, name="NewsWarmup").start()
        log.info("NewsEngine iniciado")

    def stop(self):
        self._running = False

    def _warmup(self):
        """Popula cache de notícias logo ao iniciar (sem esperar o loop)."""
        log.info("NewsEngine: warm-up iniciado")
        time.sleep(2)  # aguarda conexão de rede
        self._fetch_and_cache_news()
        symbols = self._get_symbols()
        for sym in symbols:
            try:
                self._update_sentiment(sym, force=True)
            except Exception as e:
                log.warning(f"Warm-up {sym}: {e}")
        self._update_global_sentiment()
        log.info(f"NewsEngine: warm-up concluído | {len(self._news_cache)} notícias")

    def force_refresh(self):
        """Chamado pelo botão Refresh na GUI — atualiza tudo imediatamente."""
        def _do():
            log.info("NewsEngine: refresh forçado pela GUI")
            # Invalida caches
            with self._lock:
                self._news_cache_ts = 0
                self._last_update   = {}
            self._fetch_and_cache_news()
            for sym in self._get_symbols():
                try:
                    self._update_sentiment(sym, force=True)
                except Exception as e:
                    log.warning(f"Refresh {sym}: {e}")
            self._update_global_sentiment()
            self._last_refresh_ts = time.time()
            log.info("NewsEngine: refresh concluído")
        threading.Thread(target=_do, daemon=True, name="NewsRefresh").start()

    def _get_symbols(self) -> list:
        return list(set(
            s.replace("USDT", "").replace("USD", "")
            for s in getattr(config, "TRADING_PAIRS", ["BTCUSDT"])
        ))

    def _loop(self):
        while self._running:
            for sym in self._get_symbols():
                try:
                    self._update_sentiment(sym)
                except Exception as e:
                    log.warning(f"NewsEngine loop {sym}: {e}")
                time.sleep(1.5)
            self._fetch_and_cache_news()
            self._update_global_sentiment()
            time.sleep(getattr(config, "NEWS_POLL_SEC", 120))

    # ── Sentimento por símbolo ────────────────────────────────

    def _update_sentiment(self, symbol: str, force: bool = False):
        now = time.time()
        if not force and (now - self._last_update.get(symbol, 0)) < self._cache_ttl:
            return
        sentiment = (
            self._fetch_finnhub_sentiment(symbol)
            if self._api_key
            else 0.0
        )
        with self._lock:
            self._sentiments[symbol] = sentiment
            self._last_update[symbol] = now
        log.debug(f"Sentimento {symbol}: {sentiment:+.3f}")

    def _update_global_sentiment(self):
        """Calcula sentimento GLOBAL como média ponderada de todos os pares."""
        with self._lock:
            vals = [v for k, v in self._sentiments.items() if k != "GLOBAL"]
        if not vals:
            global_sent = 0.0
        else:
            global_sent = round(sum(vals) / len(vals), 4)
        with self._lock:
            self._sentiments["GLOBAL"] = global_sent
        log.debug(f"Sentimento GLOBAL: {global_sent:+.3f}")

    def _fetch_finnhub_sentiment(self, symbol: str) -> float:
        market_type = config.MARKET_TYPE_MAP.get(
            symbol + "USDT",
            config.MARKET_TYPE_MAP.get(symbol, "crypto")
        )
        if market_type in ("crypto", "forex"):
            return self._fetch_general_news_sentiment(symbol)

        finnhub_sym = SYMBOL_MAP.get(symbol, symbol)
        url = (
            f"https://finnhub.io/api/v1/news-sentiment"
            f"?symbol={finnhub_sym}&token={self._api_key}"
        )
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data  = r.json()
                score = data.get("companyNewsScore", 0)
                buzz  = data.get("buzz", {}).get("buzz", 1.0)
                if score != 0:
                    normalized = (score - 0.5) * 2
                    return max(-1.0, min(1.0, normalized * min(buzz, 2.0)))
        except Exception:
            pass
        return self._fetch_general_news_sentiment(symbol)

    def _fetch_general_news_sentiment(self, symbol: str) -> float:
        if not self._api_key:
            return 0.0
        # Usa cache de notícias se disponível (evita request extra)
        with self._lock:
            articles = list(self._news_cache)

        if not articles:
            url = f"https://finnhub.io/api/v1/news?category=general&token={self._api_key}"
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

    # ── Cache de notícias ─────────────────────────────────────

    def _fetch_and_cache_news(self):
        """Busca e armazena feed de notícias gerais do Finnhub."""
        if not self._api_key:
            return
        now = time.time()
        if now - self._news_cache_ts < self._cache_ttl:
            return
        url = f"https://finnhub.io/api/v1/news?category=general&token={self._api_key}"
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                with self._lock:
                    self._news_cache    = r.json()
                    self._news_cache_ts = now
                log.debug(f"News cache atualizado: {len(self._news_cache)} artigos")
        except Exception as e:
            log.warning(f"_fetch_and_cache_news erro: {e}")

    # ── Getters públicos ──────────────────────────────────────

    def get_sentiment(self, symbol: str) -> float:
        clean = symbol.upper().replace("USDT", "").replace("USD", "")
        with self._lock:
            return self._sentiments.get(clean, self._sentiments.get(symbol, 0.0))

    def get_headlines(self, symbol: str) -> list:
        clean = symbol.upper().replace("USDT", "").replace("USD", "")
        with self._lock:
            return self._headlines.get(clean, [])

    def get_news_feed(self, limit: int = 20) -> list:
        """Retorna lista de notícias recentes para o painel GUI."""
        with self._lock:
            cache = list(self._news_cache)
        if cache:
            return cache[:limit]
        # Se cache vazio, tenta buscar agora (bloqueante breve)
        if self._api_key:
            self._fetch_and_cache_news()
            with self._lock:
                return self._news_cache[:limit]
        return []

    def get_last_refresh_time(self) -> str:
        """Retorna string formatada da última atualização do cache."""
        if self._news_cache_ts > 0:
            return time.strftime("%H:%M:%S", time.localtime(self._news_cache_ts))
        return "--:--:--"

    def get_event_risk(self) -> str:
        """Retorna nível de risco de evento: low | medium | high."""
        with self._lock:
            sentiments = [v for k, v in self._sentiments.items() if k != "GLOBAL"]
        if not sentiments:
            return "low"
        avg = sum(sentiments) / len(sentiments)
        if avg < -0.4:
            return "high"
        elif avg < -0.1:
            return "medium"
        return "low"