# Northstar — Binance Trading Agent

A safety-first **Binance Spot** trading agent that uses [Tauric Research TradingAgents](https://github.com/TauricResearch/TradingAgents) as its multi-agent research and portfolio-decision layer.

Northstar turns TradingAgents' five-tier portfolio rating into a separately validated Binance order plan. It adds live Binance market confirmation, confidence gating, risk-based position sizing, exchange-filter validation, an auditable SQLite run log, and a responsive operations dashboard.

> **Research software only.** This project is not financial, investment, or trading advice. LLM output can be wrong, stale, or non-deterministic. Start in paper mode, inspect every report, and use restricted API keys. You are responsible for any order sent to an exchange.

## What is included

- **TradingAgents crypto pipeline** — market, sentiment, news, bull/bear, trader, risk, and portfolio-manager agents analyze Yahoo's canonical crypto pair (for example, `BTC-USD`).
- **Binance execution gate** — the latest Binance Spot candles and 24-hour ticker validate price, indicators, volatility, balances, lot size, and minimum notional before execution.
- **Three runtime modes** — `paper` (default), Binance Spot `testnet`, and explicitly unlocked `live`.
- **Risk controls** — confidence threshold, fixed risk budget, maximum position cap, stop/take-profit plan levels, and spot-only sell behavior. No leverage or short selling.
- **Background cycles** — optional scheduled analysis, with execution independently disabled by default.
- **Auditable dashboard** — agent progress, decision reports, market chart, portfolio, risk envelope, orders, and run history.
- **No-key preview** — if no LLM key is configured, a clearly labeled deterministic technical fallback keeps paper mode usable. It does not fabricate news or sentiment.

## Decision flow

```text
Binance candles + 24h ticker
           │
           ├── TradingAgents research graph (BTC-USD / crypto mode)
           │     market → sentiment/news → bull/bear → trader → risk → PM
           │
           └── Northstar execution gate
                 confidence → balance → risk size → position cap
                 → Binance symbol filters → optional Spot market order
```

TradingAgents generates research and a rating; it does **not** receive exchange credentials and it cannot place an order directly. The broker adapter is the only component that signs Binance requests.

## Quick start: safe paper mode

Python 3.10+ is required (3.12 recommended).

```bash
git clone <this-repository>
cd Lolmutr
cp .env.example .env
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn binance_agent.app:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. Paper mode starts with 10,000 simulated USDT and requires no exchange or LLM credentials. If Binance public data is unavailable, the paper preview is marked `synthetic`; synthetic data is never used in testnet or live mode.

To install the actual TradingAgents graph and development tools:

```bash
pip install -e ".[ai,dev]"
```

The `ai` extra pins TradingAgents to `v0.3.1` so upstream changes cannot silently alter an execution deployment.

## Enable TradingAgents

Add one supported provider and its key to `.env`:

```dotenv
TRADINGAGENTS_ENABLED=true
LLM_PROVIDER=openai
DEEP_THINK_LLM=gpt-5.5
QUICK_THINK_LLM=gpt-5.4-mini
OPENAI_API_KEY=your_key_here
```

Provider names and model IDs are passed through to TradingAgents. Google, Anthropic, OpenRouter, DeepSeek, xAI, Groq, Mistral, Qwen, Zhipu, MiniMax, Ollama, and OpenAI-compatible backends can also be configured as supported by the pinned upstream version. For a local OpenAI-compatible endpoint:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BACKEND_URL=http://host.docker.internal:11434/v1
DEEP_THINK_LLM=your-model
QUICK_THINK_LLM=your-model
```

`ALLOW_DEMO_FALLBACK=true` makes an upstream provider or data failure finish with a **demo-labeled** deterministic result. Set it to `false` when an AI failure should fail the whole cycle.

## Binance modes

### Paper (default)

```dotenv
APP_MODE=paper
```

- Public Binance data, local SQLite balances, simulated 0.1% fee.
- No Binance credentials are read or required.
- Paper state is persisted in `APP_DATA_DIR/agent.sqlite3`.

### Spot Testnet

Create Spot Testnet keys and configure:

```dotenv
APP_MODE=testnet
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

The agent switches to `https://testnet.binance.vision`. Dashboard execution must still be selected for each manual cycle.

### Live Spot

Live order entry has two independent locks:

```dotenv
APP_MODE=live
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_LIVE_TRADING=true
```

A manual live request must additionally include the exact phrase `EXECUTE <SYMBOL>` (the dashboard prompts for it). Keep `BINANCE_LIVE_TRADING=false` for read-only live account access.

Recommended API-key policy:

1. Enable **Spot trading only**; never enable withdrawals.
2. Restrict the key to the server's IP where possible.
3. Use a dedicated sub-account with limited capital.
4. Keep `AUTO_EXECUTE=false` until manual testnet runs have been reviewed.
5. Monitor orders at Binance independently of this dashboard.

## Automatic cycles

Analysis scheduling and order execution are separate switches:

```dotenv
AUTO_TRADING_ENABLED=true
AGENT_INTERVAL_MINUTES=60
AUTO_EXECUTE=false
```

This configuration runs research hourly but never submits an order. Setting `AUTO_EXECUTE=true` permits eligible plans to execute. In live mode, startup rejects automatic execution unless `BINANCE_LIVE_TRADING=true` is also set.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `APP_MODE` | `paper` | `paper`, `testnet`, or `live` |
| `TRADING_SYMBOLS` | `BTCUSDT,ETHUSDT,SOLUSDT` | Comma-separated Spot watchlist |
| `BINANCE_QUOTE_ASSET` | `USDT` | Required quote for every watchlist symbol |
| `PAPER_STARTING_BALANCE` | `10000` | Initial simulated quote balance |
| `RISK_PER_TRADE_PCT` | `1.0` | Equity at risk at the planned stop |
| `MAX_POSITION_PCT` | `15.0` | Maximum value of one asset vs. equity |
| `MIN_CONFIDENCE` | `62` | Minimum derived confidence for execution |
| `STOP_LOSS_PCT` | `2.0` | Planned stop distance used for sizing |
| `TAKE_PROFIT_PCT` | `4.0` | Planned take-profit level |
| `AUTO_TRADING_ENABLED` | `false` | Enable the background timer |
| `AUTO_EXECUTE` | `false` | Allow scheduled plans to submit orders |
| `AGENT_INTERVAL_MINUTES` | `60` | Timer interval, minimum 5 minutes |
| `APP_DATA_DIR` | `./data` | SQLite and TradingAgents state directory |

See [`.env.example`](.env.example) for the complete list.

### Stop and take-profit levels

The current version uses stop-loss and take-profit levels to size and display the plan. It does **not** place a persistent OCO/bracket order at Binance. A filled market order therefore remains exposed if this service stops. Add and test venue-native protective orders before treating this as unattended production execution.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Sanitized runtime and safety status |
| `GET` | `/api/market/{symbol}` | Binance snapshot, indicators, and candles |
| `GET` | `/api/portfolio` | Marked balances and recent orders |
| `POST` | `/api/runs` | Queue analysis with optional execution |
| `GET` | `/api/runs` | Recent auditable cycles |
| `GET` | `/api/runs/{id}` | Progress and full result for one cycle |
| `POST` | `/api/paper/reset` | Reset simulated balances (paper only) |

Example analysis-only request:

```bash
curl -X POST http://localhost:8000/api/runs \
  -H 'content-type: application/json' \
  -d '{"symbol":"BTCUSDT","execute":false}'
```

The endpoint returns `202` immediately. Poll the returned run ID until `status` is `completed` or `failed`.

## Docker

The Docker image includes the TradingAgents extra:

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:8000>. Runtime state is stored in the `agent-data` volume.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

The unit tests cover indicators, risk gating/sizing, configuration validation, and atomic paper-account settlement. Tests do not call Binance or an LLM.

## Important limitations

- Spot only; no margin, futures, leverage, or short orders.
- Market orders can slip relative to the analysis snapshot.
- TradingAgents' default market vendor and Binance can differ in close time, symbol convention, and price.
- Confidence is a deterministic agreement score layered over the TradingAgents rating, not a calibrated probability.
- Local SQLite is appropriate for one process. Use a transactional service database and distributed locking before horizontally scaling.
- The control token protects state-changing endpoints but read endpoints are intentionally dashboard-accessible. Put the entire app behind a private network or authenticated reverse proxy before deployment.
- No strategy guarantees profitability.
