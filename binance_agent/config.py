from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

Mode = Literal["paper", "testnet", "live"]
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ValueError(f"{name} must be one of true/false, 1/0, yes/no, or on/off")


def _float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    mode: Mode = "paper"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    quote_asset: str = "USDT"
    api_key: str = ""
    api_secret: str = ""
    control_api_token: str = ""
    live_trading_enabled: bool = False
    auto_trading_enabled: bool = False
    auto_execute: bool = False
    interval_minutes: int = 60
    paper_starting_balance: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 15.0
    min_confidence: float = 62.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    tradingagents_enabled: bool = True
    allow_demo_fallback: bool = True
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-5.5"
    quick_think_llm: str = "gpt-5.4-mini"
    llm_backend_url: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(override=False)
        mode = os.getenv("APP_MODE", "paper").strip().lower()
        if mode not in {"paper", "testnet", "live"}:
            raise ValueError("APP_MODE must be paper, testnet, or live")

        quote = os.getenv("BINANCE_QUOTE_ASSET", "USDT").strip().upper()
        symbols = tuple(
            dict.fromkeys(
                value.strip().upper()
                for value in os.getenv(
                    "TRADING_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"
                ).split(",")
                if value.strip()
            )
        )
        if not symbols:
            raise ValueError("TRADING_SYMBOLS must include at least one symbol")
        invalid = [symbol for symbol in symbols if not _SYMBOL_RE.fullmatch(symbol)]
        if invalid:
            raise ValueError(f"Invalid Binance symbols: {', '.join(invalid)}")
        wrong_quote = [symbol for symbol in symbols if not symbol.endswith(quote)]
        if wrong_quote:
            raise ValueError(
                f"All configured symbols must end in {quote}: {', '.join(wrong_quote)}"
            )

        settings = cls(
            mode=mode,  # type: ignore[arg-type]
            host=os.getenv("APP_HOST", "0.0.0.0"),
            port=_int("APP_PORT", 8000, minimum=1, maximum=65535),
            log_level=os.getenv("APP_LOG_LEVEL", "INFO").upper(),
            data_dir=Path(os.getenv("APP_DATA_DIR", "./data")).expanduser().resolve(),
            symbols=symbols,
            quote_asset=quote,
            api_key=os.getenv("BINANCE_API_KEY", "").strip(),
            api_secret=os.getenv("BINANCE_API_SECRET", "").strip(),
            control_api_token=os.getenv("CONTROL_API_TOKEN", "").strip(),
            live_trading_enabled=_bool("BINANCE_LIVE_TRADING", False),
            auto_trading_enabled=_bool("AUTO_TRADING_ENABLED", False),
            auto_execute=_bool("AUTO_EXECUTE", False),
            interval_minutes=_int(
                "AGENT_INTERVAL_MINUTES", 60, minimum=5, maximum=10_080
            ),
            paper_starting_balance=_float(
                "PAPER_STARTING_BALANCE", 10_000, minimum=10, maximum=1_000_000_000
            ),
            risk_per_trade_pct=_float(
                "RISK_PER_TRADE_PCT", 1.0, minimum=0.01, maximum=5.0
            ),
            max_position_pct=_float(
                "MAX_POSITION_PCT", 15.0, minimum=0.1, maximum=100.0
            ),
            min_confidence=_float(
                "MIN_CONFIDENCE", 62, minimum=0, maximum=100
            ),
            stop_loss_pct=_float("STOP_LOSS_PCT", 2.0, minimum=0.1, maximum=25),
            take_profit_pct=_float(
                "TAKE_PROFIT_PCT", 4.0, minimum=0.1, maximum=100
            ),
            tradingagents_enabled=_bool("TRADINGAGENTS_ENABLED", True),
            allow_demo_fallback=_bool("ALLOW_DEMO_FALLBACK", True),
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            deep_think_llm=os.getenv("DEEP_THINK_LLM", "gpt-5.5").strip(),
            quick_think_llm=os.getenv("QUICK_THINK_LLM", "gpt-5.4-mini").strip(),
            llm_backend_url=os.getenv("LLM_BACKEND_URL", "").strip() or None,
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.validate_execution_safety()
        return settings

    def validate_execution_safety(self) -> None:
        if self.mode in {"testnet", "live"} and (not self.api_key or not self.api_secret):
            raise ValueError(
                f"BINANCE_API_KEY and BINANCE_API_SECRET are required in {self.mode} mode"
            )
        if self.mode == "live" and len(self.control_api_token) < 24:
            raise ValueError(
                "Live mode requires CONTROL_API_TOKEN with at least 24 characters"
            )
        if self.mode == "live" and self.auto_execute and not self.live_trading_enabled:
            raise ValueError(
                "AUTO_EXECUTE in live mode requires BINANCE_LIVE_TRADING=true"
            )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.sqlite3"

    @property
    def binance_base_url(self) -> str:
        if self.mode == "testnet":
            return "https://testnet.binance.vision"
        return "https://api.binance.com"

    @property
    def public_market_url(self) -> str:
        # Mainnet public data gives paper mode realistic prices. Testnet/live use
        # their matching venue so execution validation sees the same order book.
        return self.binance_base_url

    @property
    def ai_configured(self) -> bool:
        if not self.tradingagents_enabled:
            return False
        if self.llm_provider in {"ollama", "openai_compatible"}:
            return bool(self.llm_backend_url)
        env_name = _PROVIDER_KEYS.get(self.llm_provider)
        return bool(env_name and os.getenv(env_name, "").strip())

    @property
    def intelligence_mode(self) -> str:
        return "TradingAgents" if self.ai_configured else "Demo intelligence"
