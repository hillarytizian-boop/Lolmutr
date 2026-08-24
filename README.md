# Lolmutr — Binance desk on TradingAgents

A crypto trading firm in software. The [Tauric Research TradingAgents](https://github.com/TauricResearch/TradingAgents) graph — analysts, bull/bear researchers, trader, risk committee, portfolio manager — is wired to **Binance spot**.

**Signals always come from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).** Setup clones that repo into `vendor/TradingAgents`. The Portfolio Manager seat is the only source of BUY/SELL/HOLD. Binance adapters are the eyes and hands. A deterministic risk gate can block a ticket; it cannot invent a BUY.

If no LLM key is set, every cycle is **HOLD**. A failed LLM call is **ANALYSIS FAILED**, never a silent HOLD. Nothing else will invent a trade.

Default book is a **$10 stake compounding toward a $50 goal**. That is a target, not a forecast.

> Not financial advice. DEMO/paper is the default. Live trading stays locked until you set `BINANCE_LIVE_CONFIRM=I_UNDERSTAND` (or `LIVE_TRADING_CONFIRM=true`). Agents can be wrong.

## Termux — clone, keys, auto-trade

```bash
pkg update -y
pkg install -y git python
pkg install -y termux-api   # optional wake-lock

git clone -b arena/01a01418-lolmutr https://github.com/hillarytizian-boop/Lolmutr.git
cd Lolmutr
# If a previous run died on pydantic-core / Rust:
rm -rf .venv
bash scripts/termux-setup.sh
```

The script installs a venv (always use `.venv/bin/python`), then asks:

1. **LLM provider** — default `nvidia` (GLM-5.2 at `https://integrate.api.nvidia.com/v1`)
2. **NVIDIA_API_KEY** — paste the `nvapi-...` key (not the Binance key)
3. **Trading mode** — `demo` (default) / `testnet` / `live`
4. **Binance API key + secret** — required for testnet or live
5. **Live unlock** — type `I_UNDERSTAND` or it forces DEMO
6. **Watchlist + loop minutes**

Then it starts `python -m app trade`.

```
MODE: DEMO
EXCHANGE AUTHENTICATION: NOT REQUIRED
BRAIN: TradingAgents
```

Later sessions:

```bash
cd ~/Lolmutr
. .venv/bin/activate
python -m app trade          # Rich cockpit autotrader
python -m app once           # one cycle and exit
python -m app test           # DEMO self-check (no live orders)
python -m app serve          # web desk (needs requirements-web.txt)
```

Binance key permissions: **spot read + spot trade only**. Do not enable withdrawals.

## Pipeline

```
MARKET DATA → TradingAgents BRAIN → DECISION → RISK ENGINE
    → ORDER EXECUTION → POSITION MONITOR → SL/TP → BALANCE → DASHBOARD
```

- **Eyes**: Binance public market data (price, OHLCV, book, multi-timeframe). DEMO tape only when mode is demo/paper and Binance is unreachable. LIVE never fabricates prices.
- **Brain**: TradingAgents seats only (market, sentiment, news, bull, bear, trader, risk, portfolio manager).
- **Safety**: deterministic gate (balance, size, daily loss, exposure, stale data, cooldown, duplicates).
- **Hands**: paper broker in DEMO; signed Binance only when live is unlocked.
- **Memory**: paper book + `data/cockpit.json`. On LIVE the exchange is authoritative.
- **Cockpit**: Rich terminal. Termux uses a one-screen redraw so the phone is not flooded.

## Terminal controls

```
q quit   p pause (analysis on, execution off)   r resume
s strategy   m market   o positions   t trades   l logs   h help
e emergency stop (cancel entry orders, keep monitoring, no auto-resume)
```

Stop the loop with Ctrl+C or `touch data/HALT`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `demo` | `demo` / `paper` / `testnet` / `live` |
| `STAKE_USD` | `10` | starting book |
| `GOAL_USD` | `50` | lock the book when equity hits this |
| `WATCHLIST` | `BTCUSDT,ETHUSDT,SOLUSDT` | pairs the loop scans |
| `LOOP_SECONDS` | `900` | sleep between analysis cycles |
| `MIN_CONFIDENCE` | `0.58` | skip weaker tickets **when PM emitted a number** |
| `MAX_DAILY_LOSS_PCT` | `15` | halt new tickets for the UTC day |
| `AUTO_EXECUTE` | `true` | `false` = analyze only |
| `RISK_PER_TRADE` | `0.02` | fraction of equity risked to the stop |
| `MAX_POSITION_PERCENT` | `0.90` | never 100% of the account |
| `MIN_NOTIONAL` | `5` | below this → ORDER BLOCKED |
| `BINANCE_LIVE_CONFIRM` | empty | must be `I_UNDERSTAND` (or `LIVE_TRADING_CONFIRM=true`) for live |
| `NVIDIA_API_KEY` | empty | GLM-5.2 key (`nvapi-...`) |
| `LLM_PROVIDER` | `nvidia` | `nvidia` / `groq` / `openai` / … |

Aliases: `EXCHANGE_API_KEY` → `BINANCE_API_KEY`, `NVIDIA_NIM_API_KEY` / `NVAPI_KEY` → `NVIDIA_API_KEY`.

## Demo / live

```bash
# DEMO (default) — paper wallet, no real orders
TRADING_MODE=demo python -m app trade

# LIVE — real funds, extra confirm required
TRADING_MODE=live BINANCE_LIVE_CONFIRM=I_UNDERSTAND python -m app trade
```

If `TRADING_MODE=live` but the confirm phrase is missing, the desk **forces DEMO**.

## Tests

```bash
. .venv/bin/activate
python -m pytest -q
python -m app test
```

## Disclaimer

Research software. LLM output is non-deterministic, crypto is volatile, and an unattended live loop can lose money. Start on DEMO. Size live accounts as if the agent will be wrong.
