"""Runtime configuration. Secrets stay in the environment; never in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

VALID_MODES = ("paper", "testnet", "live")
BINANCE_SPOT = "https://api.binance.com"
BINANCE_TESTNET = "https://testnet.binance.vision"
LIVE_CONFIRM_PHRASE = "I_UNDERSTAND"

DEFAULT_WATCHLIST = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
)

AUTO_WATCHLIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

DATA_DIR = Path(os.getenv("LOLMUTR_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
HALT_FILE = DATA_DIR / "HALT"


def load_env(*, override: bool = False) -> None:
    load_dotenv(ROOT / ".env", override=override)


def reload_env() -> None:
    load_env(override=True)


load_env()


def _mode() -> str:
    raw = (os.getenv("TRADING_MODE") or "paper").strip().lower()
    return raw if raw in VALID_MODES else "paper"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _watchlist() -> tuple[str, ...]:
    raw = (os.getenv("WATCHLIST") or "").strip()
    if not raw:
        return AUTO_WATCHLIST
    from app.binance.symbols import to_binance

    out: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(to_binance(part))
        except ValueError:
            continue
    return tuple(out) or AUTO_WATCHLIST


@dataclass(frozen=True)
class Settings:
    trading_mode: str
    paper_starting_cash: float
    binance_api_key: str
    binance_api_secret: str
    live_confirm: str
    host: str
    port: int
    watchlist: tuple[str, ...]
    interval: str
    loop_seconds: int
    min_confidence: float
    max_positions: int
    max_daily_loss_pct: float
    cooldown_minutes: int
    auto_execute: bool
    llm_provider: str
    llm_model: str
    llm_base_url: str
    manage_seconds: int
    trail_atr: float
    profit_mode: bool
    stake_usd: float
    goal_usd: float
    min_notional: float

    @property
    def small_account(self) -> bool:
        return self.stake_usd <= 50 or self.paper_starting_cash <= 50

    @property
    def binance_rest(self) -> str:
        if self.trading_mode == "testnet":
            return BINANCE_TESTNET
        return BINANCE_SPOT

    @property
    def public_rest(self) -> str:
        return BINANCE_SPOT

    @property
    def live_unlocked(self) -> bool:
        return (
            self.trading_mode == "live"
            and self.live_confirm == LIVE_CONFIRM_PHRASE
            and bool(self.binance_api_key and self.binance_api_secret)
        )

    @property
    def signed_ready(self) -> bool:
        if self.trading_mode == "paper":
            return False
        if not (self.binance_api_key and self.binance_api_secret):
            return False
        if self.trading_mode == "live":
            return self.live_unlocked
        return True


def get_settings() -> Settings:
    return Settings(
        trading_mode=_mode(),
        paper_starting_cash=float(os.getenv("PAPER_STARTING_CASH") or os.getenv("STAKE_USD") or 10),
        binance_api_key=(os.getenv("BINANCE_API_KEY") or "").strip(),
        binance_api_secret=(os.getenv("BINANCE_API_SECRET") or "").strip(),
        live_confirm=(os.getenv("BINANCE_LIVE_CONFIRM") or "").strip(),
        host=os.getenv("HOST") or "0.0.0.0",
        port=int(os.getenv("PORT") or 8000),
        watchlist=_watchlist(),
        interval=(os.getenv("INTERVAL") or "1h").strip(),
        loop_seconds=int(os.getenv("LOOP_SECONDS") or 900),
        min_confidence=float(os.getenv("MIN_CONFIDENCE") or 0.58),
        max_positions=int(os.getenv("MAX_POSITIONS") or 1),
        max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT") or 15.0),
        cooldown_minutes=int(os.getenv("COOLDOWN_MINUTES") or 20),
        auto_execute=_bool("AUTO_EXECUTE", True),
        llm_provider=(os.getenv("LLM_PROVIDER") or "").strip().lower(),
        llm_model=(os.getenv("LLM_MODEL") or "").strip(),
        llm_base_url=(os.getenv("LLM_BASE_URL") or "").strip(),
        manage_seconds=int(os.getenv("MANAGE_SECONDS") or 60),
        trail_atr=float(os.getenv("TRAIL_ATR") or 1.8),
        profit_mode=_bool("PROFIT_MODE", True),
        stake_usd=float(os.getenv("STAKE_USD") or os.getenv("PAPER_STARTING_CASH") or 10),
        goal_usd=float(os.getenv("GOAL_USD") or 50),
        min_notional=float(os.getenv("MIN_NOTIONAL") or 5),
    )
