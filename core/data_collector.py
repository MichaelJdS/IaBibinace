"""
Agente de Coleta de Dados
- Candles: Binance REST API (gratuito, sem restrição)
- Sinal agregado: calculado localmente pelo bot (RSI + MACD)
- Finnhub: usado apenas para dados de mercado extras (opcional)
"""
import requests
import pandas as pd
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from utils.logger import get_logger

log = get_logger("DataCollector")

class DataCollector:
    def __init__(self):
        # Endpoint público da Binance para candles (sem autenticação)
        self.binance_base = config.BINANCE_ENDPOINTS[config.TRADING_MODE]["rest"]
        log.info("DataCollector inicializado ✅")

    def get_candles(self, periods: int = 100) -> pd.DataFrame:
        """
        Busca candles OHLCV diretamente da Binance REST API.
        Endpoint público — não precisa de chave nem assinatura.
        """
        # Mapeamento de timeframe (minutos → string Binance)
        tf_map = {
            "1": "1m", "3": "3m", "5": "5m", "15": "15m",
            "30": "30m", "60": "1h", "D": "1d", "W": "1w"
        }
        interval = tf_map.get(config.TIMEFRAME, "15m")

        try:
            url    = f"{self.binance_base}/api/v3/klines"
            params = {
                "symbol"  : config.SYMBOL_BINANCE,
                "interval": interval,
                "limit"   : periods
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            raw = r.json()

            df = pd.DataFrame(raw, columns=[
                "time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            df["time"]   = pd.to_datetime(df["time"], unit="ms")
            df["open"]   = df["open"].astype(float)
            df["high"]   = df["high"].astype(float)
            df["low"]    = df["low"].astype(float)
            df["close"]  = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            df = df[["time", "open", "high", "low", "close", "volume"]]

            log.info(
                f"Candles: {len(df)} velas [{interval}] | "
                f"Último preço: ${df['close'].iloc[-1]:,.2f}"
            )
            return df

        except Exception as e:
            log.error(f"Erro ao coletar candles: {e}")
            return pd.DataFrame()

    def get_aggregate_signal(self) -> dict:
        """
        Sinal agregado calculado localmente pelo bot.
        O Finnhub aggregate_indicator exige plano pago (403).
        Retorna 'pending' — a estratégia usará só os indicadores locais.
        """
        return {"signal": "neutral", "raw": {}}

    def get_current_price(self) -> float:
        """Retorna preço atual do par via ticker público."""
        try:
            url = f"{self.binance_base}/api/v3/ticker/price"
            r   = requests.get(url, params={"symbol": config.SYMBOL_BINANCE}, timeout=10)
            r.raise_for_status()
            price = float(r.json()["price"])
            log.info(f"Preço atual {config.SYMBOL_BINANCE}: ${price:,.2f}")
            return price
        except Exception as e:
            log.error(f"Erro ao buscar preço: {e}")
            return 0.0