# Lolmutr — Binance desk on TradingAgents

A crypto trading firm in software. The [Tauric Research TradingAgents](https://github.com/TauricResearch/TradingAgents) graph — analysts, bull/bear researchers, trader, risk committee, portfolio manager — is wired to **Binance spot**.

Default book is a **$10 stake compounding toward a $50 goal**. One position at a time, ~90% of cash on a clean Buy, winners trail, book locks when $50 is hit. That is a target, not a forecast.

> Not financial advice. Paper is the default. Live trading stays locked until you type `I_UNDERSTAND`. Agents can be wrong.

## Termux — clone, keys, auto-trade

```bash
pkg update -y
pkg install -y git python
# optional: keep the CPU awake while the loop runs
pkg install -y termux-api

git clone -b arena/01a01418-lolmutr https://github.com/hillarytizian-boop/Lolmutr.git
cd Lolmutr
# If a previous run died on pydantic-core / Rust:
rm -rf .venv
bash scripts/termux-setup.sh
```

The script installs a venv, then asks:

1. **LLM provider** — `groq` (free tier, good on a phone), `openai`, `openrouter`, `deepseek`, `gemini`, or `none`
2. **API key** — pasted hidden
3. **Trading mode** — `paper` (default) / `testnet` / `live`
4. **Binance API key + secret** — required for testnet or live
5. **Live unlock** — type `I_UNDERSTAND` or it forces paper
6. **Watchlist + loop minutes**

Then it starts `python -m app trade`.

```
[cycle 1] BTCUSDT  Buy   conf=0.71  FILL 0.007 @ 108450 on paper
          ETHUSDT  Hold  skip (hold)
sleeping 900s     Ctrl+C or  touch data/HALT  to stop
```

Later sessions:

```bash
cd ~/Lolmutr
. .venv/bin/activate
python -m app trade          # autotrader
python -m app once           # one cycle
python -m app serve          # web desk
```

Binance key permissions: **spot read + spot trade only**. Do not enable withdrawals.

## What the loop does

The TradingAgents firm picks the trade. A profit layer then manages the open long so winners get banked instead of given back:

- **$10 → $50 stake**: one ticket, ~92% of cash, compound after every fill
- **No early take-profit** on a small book — the trail lets a winner run toward the goal
- **Hard stop** at 1.6 ATR so one loser does not have to be zero
- **Goal lock** at $50 — the loop stops and keeps the cash
- Closed-trade PnL is fed back into the next PM vote

Every `LOOP_SECONDS` (default 15 minutes) the firm votes. Every `MANAGE_SECONDS` (default 60s) stops and targets are checked. If the PM rating clears the gates, it fills:

| Gate | Default |
|---|---|
| Minimum PM confidence | 0.58 |
| Max open names | 1 ($10 book) |
| Daily loss circuit breaker | −15% of start-of-day equity |
| Cooldown per symbol | 20 minutes |
| No pyramiding | skip Buy if already long |
| Live lock | `BINANCE_LIVE_CONFIRM=I_UNDERSTAND` |

The LLM (when a key is set) re-rates the finished analyst book as Portfolio Manager. If the model is down, the native heuristic rating is used. If `tradingagents` is installed, the official crypto graph can overlay as well.

## Desktop / web

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app serve
```

```bash
python -m pytest -q
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `paper` | `paper` / `testnet` / `live` |
| `STAKE_USD` | `10` | starting book |
| `GOAL_USD` | `50` | lock the book when equity hits this |
| `WATCHLIST` | `BTCUSDT,ETHUSDT,SOLUSDT` | pairs the loop scans |
| `LOOP_SECONDS` | `900` | sleep between cycles |
| `MIN_CONFIDENCE` | `0.58` | skip weaker tickets |
| `MAX_DAILY_LOSS_PCT` | `5` | halt new tickets for the UTC day |
| `AUTO_EXECUTE` | `true` | `false` = analyze only |
| `MANAGE_SECONDS` | `60` | how often stops / targets are checked |
| `TRAIL_ATR` | `1.4` | trailing-stop distance in ATRs |
| `PROFIT_MODE` | `true` | conviction-weighted size, TP/SL/trail on |
| `BINANCE_LIVE_CONFIRM` | empty | must be `I_UNDERSTAND` for live |
| `LLM_PROVIDER` | empty | `groq` / `openai` / `openrouter` / … |

## Disclaimer

Research software. LLM output is non-deterministic, crypto is volatile, and an unattended live loop can lose money. Start on paper. Size live accounts as if the agent will be wrong.
