# ⚡ CRYPTO IA BOT v2

Bot de trading algorítmico com IA multi-agente (Groq Council),
análise técnica ensemble, Finnhub news e painel PyQt6.

## Estrutura

CRYPTO_IA_BOT_v2/
├── config.py              ← Configurações (edite antes de rodar)
├── main.py                ← Modo CLI (headless)
├── main_gui.py            ← Modo painel PyQt6
├── requirements.txt
├── agents/
│   └── brain_agent.py     ← Orquestrador principal
├── core/
│   ├── binance_ws.py      ← WebSocket Binance (preços + candles)
│   ├── indicators.py      ← RSI, MACD, BB, ATR, EMA, VWAP
│   ├── order_executor.py  ← Execução de ordens (demo/testnet/live)
│   ├── groq_council.py    ← 3 agentes Groq: analyze/validate/explain
│   ├── news_engine.py     ← Finnhub news + sentimento
│   ├── risk_engine.py     ← SL/TP/Trailing, Kelly sizing, cooldown
│   ├── adaptive_engine.py ← Auto-ajuste de parâmetros
│   └── database.py        ← SQLite: trades, AI decisions, snapshots
├── strategies/
│   └── ensemble.py        ← 4 estratégias: Trend+MR+Breakout+Momentum
├── gui/
│   └── main_window.py     ← Painel 6 abas PyQt6
└── utils/
    └── logger.py          ← Logger colorido

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Edite config.py com suas chaves API
# Rode com painel:
python main_gui.py

# Ou modo CLI:
python main.py
```

## Modos

| Modo     | Ordens reais | Dinheiro real | Ideal para       |
|----------|-------------|---------------|------------------|
| demo     | Não         | Não           | Testar lógica    |
| testnet  | Sim         | Não           | Testar execução  |
| live     | Sim         | SIM ⚠️        | Produção         |

## Fluxo de decisão

Ticks WS → Candles → Indicadores → Ensemble (4 estratégias)
→ Groq Analyzer → Groq Validator → Groq Explainer
→ Risk Engine → Order Executor → Database → Adaptive Engine