"""
config.py — Configuração central do bot
Versão unificada com suporte multi-mercado (Crypto + Forex)
e compatibilidade total com todos os módulos existentes.
"""
import os

# ── Ambiente ─────────────────────────────────────────────────
TRADING_MODE = os.getenv("TRADING_MODE", "DEMO").upper()
DEBUG = os.getenv("DEBUG", "1") == "1"

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE", "logs/bot.log")

# ── Mercado / símbolos ────────────────────────────────────────────
PRIMARY_PAIR = os.getenv("PRIMARY_PAIR", "BTCUSDT")

# Operação apenas em cripto (Binance Demo)
CRYPTO_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
]

FOREX_PAIRS  = []   # forex removido — Binance não suporta

TRADING_PAIRS = CRYPTO_PAIRS

MARKET_TYPE_MAP = {
    "BTCUSDT": "crypto",
    "ETHUSDT": "crypto",
    "SOLUSDT": "crypto",
    "BNBUSDT": "crypto",
}

# ── Timeframes ────────────────────────────────────────────────
TF_PRIMARY = os.getenv("TF_PRIMARY", "1m")
TF_CONFIRM = os.getenv("TF_CONFIRM", "5m")
TF_TREND   = os.getenv("TF_TREND",   "15m")

# Aliases legados usados por binance_ws e outros módulos antigos
TF_FAST   = os.getenv("TF_FAST",   "1m")
TF_SLOW   = os.getenv("TF_SLOW",   "5m")
TF_HIGHER = os.getenv("TF_HIGHER", "15m")

CANDLE_LIMIT = 300

# ── Loop / ciclo ──────────────────────────────────────────────
CYCLE_SLEEP            = float(os.getenv("CYCLE_SLEEP",            "1.0"))
NEWS_POLL_SEC          = int(os.getenv("NEWS_POLL_SEC",            "120"))
GROQ_ANALYSIS_INTERVAL = int(os.getenv("GROQ_ANALYSIS_INTERVAL",  "15"))

# ── Execução ──────────────────────────────────────────────────
MAX_OPEN_POSITIONS     = int(os.getenv("MAX_OPEN_POSITIONS",       "4"))
MAX_POSITIONS          = int(os.getenv("MAX_POSITIONS",            "4"))   # alias legado
MAX_POSITIONS_PER_MARKET = int(os.getenv("MAX_POSITIONS_PER_MARKET", "2"))
ALLOW_SHORTS           = os.getenv("ALLOW_SHORTS", "False").lower() == "true"

# ── Risco ─────────────────────────────────────────────────────
RISK_PER_TRADE_PCT     = float(os.getenv("RISK_PER_TRADE_PCT",    "0.008"))
MAX_DAILY_LOSS_PCT     = float(os.getenv("MAX_DAILY_LOSS_PCT",    "0.04"))
MAX_WEEKLY_LOSS_PCT    = float(os.getenv("MAX_WEEKLY_LOSS_PCT",   "0.10"))
DAILY_LOSS_LIMIT_PCT   = float(os.getenv("DAILY_LOSS_LIMIT_PCT",  "0.04"))  # alias
MIN_RR                 = float(os.getenv("MIN_RR",                "1.4"))
COOLDOWN_AFTER_LOSS_MIN = int(os.getenv("COOLDOWN_AFTER_LOSS_MIN","5"))
COOLDOWN_SECONDS       = int(os.getenv("COOLDOWN_SECONDS",        "300"))   # alias legado
SL_ATR_MULT            = float(os.getenv("SL_ATR_MULT",           "1.4"))
TP_ATR_MULT            = float(os.getenv("TP_ATR_MULT",           "2.2"))
TRAILING_ATR_MULT      = float(os.getenv("TRAILING_ATR_MULT",     "1.0"))

# Aliases legados de risco
STOP_LOSS_PCT          = float(os.getenv("STOP_LOSS_PCT",         "0.015"))
TAKE_PROFIT_PCT        = float(os.getenv("TAKE_PROFIT_PCT",       "0.025"))
TRAILING_STOP_PCT      = float(os.getenv("TRAILING_STOP_PCT",     "0.01"))
POSITION_SIZE_PCT      = float(os.getenv("POSITION_SIZE_PCT",     "0.10"))
MIN_TRADE_USDT         = float(os.getenv("MIN_TRADE_USDT",        "25"))
MIN_NOTIONAL           = float(os.getenv("MIN_NOTIONAL",          "10"))
MAX_ORDER_USDT         = float(os.getenv("MAX_ORDER_USDT",        "100.0"))  # Valor máximo por ordem em USDT

# ── Thresholds de decisão ─────────────────────────────────────
CONFIDENCE_THRESHOLD      = int(os.getenv("CONFIDENCE_THRESHOLD",      "52"))
MIN_CONFIDENCE_TO_TRADE   = int(os.getenv("MIN_CONFIDENCE_TO_TRADE",   "50"))
ENSEMBLE_BASE_THRESHOLD   = float(os.getenv("ENSEMBLE_BASE_THRESHOLD", "2.4"))
RANGING_THRESHOLD         = float(os.getenv("RANGING_THRESHOLD",       "3.0"))
TRENDING_THRESHOLD        = float(os.getenv("TRENDING_THRESHOLD",      "2.2"))

# ── Indicadores ───────────────────────────────────────────────
RSI_PERIOD     = int(os.getenv("RSI_PERIOD",   "14"))
RSI_OVERSOLD   = int(os.getenv("RSI_OVERSOLD", "30"))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT","70"))

MACD_FAST   = int(os.getenv("MACD_FAST",   "12"))
MACD_SLOW   = int(os.getenv("MACD_SLOW",   "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))

BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD    = float(os.getenv("BB_STD",   "2.0"))

ATR_PERIOD      = int(os.getenv("ATR_PERIOD",      "14"))
STOCH_RSI_PERIOD = int(os.getenv("STOCH_RSI_PERIOD","14"))
ADX_PERIOD      = int(os.getenv("ADX_PERIOD",      "14"))

# ── APIs ──────────────────────────────────────────────────────
# Groq
GROQ_API_KEYS  = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
GROQ_MODEL_FAST  = os.getenv("GROQ_MODEL_FAST",  "llama-3.1-8b-instant")
GROQ_MODEL_MAIN  = os.getenv("GROQ_MODEL_MAIN",  "llama-3.3-70b-versatile")
GROQ_MODEL_HEAVY = os.getenv("GROQ_MODEL_HEAVY", "llama-3.3-70b-versatile")

# Binance
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Finnhub
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# Telegram
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Forex / OANDA
FOREX_PROVIDER    = os.getenv("FOREX_PROVIDER",    "YFINANCE").upper()
OANDA_API_KEY     = os.getenv("OANDA_API_KEY",     "")
OANDA_ACCOUNT_ID  = os.getenv("OANDA_ACCOUNT_ID",  "")

# ── Custos estimados ──────────────────────────────────────────
FEE_RATE_CRYPTO  = float(os.getenv("FEE_RATE_CRYPTO",  "0.0008"))
FEE_RATE_FOREX   = float(os.getenv("FEE_RATE_FOREX",   "0.0002"))
SLIPPAGE_CRYPTO  = float(os.getenv("SLIPPAGE_CRYPTO",  "0.0005"))
SLIPPAGE_FOREX   = float(os.getenv("SLIPPAGE_FOREX",   "0.0001"))

BINANCE_ENDPOINTS = {
    "DEMO": {
        "rest":      "https://demo-api.binance.com",
        "ws":        "wss://demo-ws-api.binance.com/ws-api/v3",
        "ws_stream": "wss://demo-stream.binance.com",
    },
    "REAL": {
        "rest":      "https://api.binance.com",
        "ws":        "wss://ws-api.binance.com/ws-api/v3",
        "ws_stream": "wss://stream.binance.com:9443",
    }
}