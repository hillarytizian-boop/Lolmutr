# Lolmutr — Binance desk on TradingAgents

A crypto trading firm in software. The [Tauric Research TradingAgents](https://github.com/TauricResearch/TradingAgents) graph — analysts, bull/bear researchers, trader, risk committee, portfolio manager — is wired to **Binance spot** instead of Yahoo-finance equities.

Default venue is a **paper book** marked to live Binance last prices. Testnet is optional. Live trading stays locked unless you set an explicit confirm phrase.

> Not financial advice. The original TradingAgents authors designed the framework for research; this desk is the same kind of experiment.

## What it does

1. Pulls live USDT-perp-quality spot data from Binance public REST (`ticker`, `klines`, `depth`).
2. Runs the TradingAgents firm locally:
   - **Market Analyst** — RSI, MACD, EMA stack, Bollinger, ATR, volume
   - **Sentiment Analyst** — Crypto Fear & Greed (contrarian) + headline tone
   - **News Analyst** — public crypto wire
   - **Market Structure** — book imbalance / range (crypto stand-in for equity fundamentals; TradingAgents also drops fundamentals in crypto mode)
   - **Bull / Bear researchers** debate, **Research Manager** writes a 5-tier plan
   - **Trader** issues Buy / Hold / Sell
   - **Risk committee** haircuts size by realized vol
   - **Portfolio Manager** publishes Buy / Overweight / Hold / Underweight / Sell
3. Optionally paper-fills the ticket at Binance last (10 bps fee).
4. If you `pip install .[tradingagents]` and export an LLM key, the official `TradingAgentsGraph.propagate(ticker, date, asset_type="crypto")` run is folded in. `BTCUSDT` is mapped to `BTC-USD` for that graph.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app
```

Open the printed URL. Pick a pair, hit **Run desk**.

If the host cannot complete TLS to `api.binance.com` (some sandboxes), the desk
falls back to a deterministic demo tape so the firm, chart, and paper book stay
interactive. Local machines that can reach Binance never see that fallback.

```bash
# just the tests
pip install pytest
python -m pytest -q
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `paper` | `paper` / `testnet` / `live` |
| `PAPER_STARTING_CASH` | `10000` | USDT in the paper book |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | empty | needed only for testnet or live |
| `BINANCE_LIVE_CONFIRM` | empty | must be `I_UNDERSTAND` before any live order is signed |
| `OPENAI_API_KEY` (or Anthropic / Gemini / …) | empty | unlocks the official TradingAgents graph |

Live mode is refused even if keys are present, unless the confirm phrase is set. The dashboard never asks for secrets.

## Architecture

```
web/                 dashboard (Sora + IBM Plex Mono, Binance gold)
app/main.py          FastAPI — /api/analyze, markets, portfolio
app/agents/graph.py  firm orchestrator (TradingAgents shape)
app/binance/         public REST, indicators, paper broker, signed exec
```

Symbol bridge: `BTCUSDT` ↔ `BTC-USD` lives in `app/binance/symbols.py`, matching TradingAgents’ crypto ticker convention.

## Disclaimer

This is research software. Agents can be wrong, LLM output is non-deterministic, and crypto is volatile. Use paper mode. Do not size real money off an unattended loop.
