"""Runtime configuration. Secrets stay in the environment; never in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

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

DATA_DIR = Path(os.getenv("LOLMUTR_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _mode() -> str:
    raw = (os.getenv("TRADING_MODE") or "paper").strip().lower()
    return raw if raw in VALID_MODES else "paper"


@dataclass(frozen=True)
class Settings:
    trading_mode: str
    paper_starting_cash: float
    binance_api_key: str
    binance_api_secret: str
    live_confirm: str
    host: str
    port: int

    @property
    def binance_rest(self) -> str:
        if self.trading_mode == "testnet":
            return BINANCE_TESTNET
        return BINANCE_SPOT

    @property
    def public_rest(self) -> str:
        # Market data always comes from production so the desk stays live
        # even when paper-trading or using an empty testnet book.
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
        paper_starting_cash=float(os.getenv("PAPER_STARTING_CASH") or 10_000),
        binance_api_key=(os.getenv("BINANCE_API_KEY") or "").strip(),
        binance_api_secret=(os.getenv("BINANCE_API_SECRET") or "").strip(),
        live_confirm=(os.getenv("BINANCE_LIVE_CONFIRM") or "").strip(),
        host=os.getenv("HOST") or "0.0.0.0",
        port=int(os.getenv("PORT") or 8000),
    )
