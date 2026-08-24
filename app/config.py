"""Runtime configuration. Secrets stay in the environment; never in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(*, override: bool = False) -> None:
    """Load KEY=value lines from .env. No python-dotenv required."""
    path = ROOT / ".env"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = val
    alias_secrets()


def alias_secrets() -> None:
    """Accept common aliases without inventing values."""
    pairs = (
        ("NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY"),
        ("NVAPI_KEY", "NVIDIA_API_KEY"),
        ("EXCHANGE_API_KEY", "BINANCE_API_KEY"),
        ("EXCHANGE_API_SECRET", "BINANCE_API_SECRET"),
        ("BINANCE_KEY", "BINANCE_API_KEY"),
        ("BINANCE_SECRET", "BINANCE_API_SECRET"),
        ("LIVE_TRADING_CONFIRM", "BINANCE_LIVE_CONFIRM"),
    )
    for src, dst in pairs:
        src_val = (os.getenv(src) or "").strip().strip('"').strip("'")
        dst_val = (os.getenv(dst) or "").strip().strip('"').strip("'")
        if src_val and not dst_val:
            os.environ[dst] = src_val


VALID_MODES = ("paper", "demo", "testnet", "live")
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
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
HALT_FILE = DATA_DIR / "HALT"


def reload_env() -> None:
    load_env(override=True)
    alias_secrets()


load_env()


def _mode() -> str:
    raw = (os.getenv("TRADING_MODE") or "paper").strip().lower()
    if raw in {"demo", "paper"}:
        return "paper"
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


def _live_confirm_ok() -> bool:
    confirm = (
        os.getenv("BINANCE_LIVE_CONFIRM") or os.getenv("LIVE_TRADING_CONFIRM") or ""
    ).strip()
    if confirm == LIVE_CONFIRM_PHRASE:
        return True
    return confirm.lower() in {"true", "1", "yes", "on"}


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
    risk_per_trade: float
    max_position_percent: float
    max_exposure: float
    unprotected_policy: str

    @property
    def small_account(self) -> bool:
        return self.stake_usd <= 50 or self.paper_starting_cash <= 50

    @property
    def display_mode(self) -> str:
        if self.trading_mode == "live" and self.live_unlocked:
            return "LIVE"
        if self.trading_mode == "testnet":
            return "TESTNET"
        return "DEMO"

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
            and _live_confirm_ok()
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

    @property
    def allow_demo_tape(self) -> bool:
        """Fabricated demo prices are only legal in paper/demo mode."""
        return self.trading_mode == "paper"


def get_settings() -> Settings:
    alias_secrets()
    max_pos_default = "0.90" if _bool("PROFIT_MODE", True) else "0.25"
    stake = float(os.getenv("STAKE_USD") or os.getenv("PAPER_STARTING_CASH") or 10)
    if stake > 50:
        max_pos_default = os.getenv("MAX_POSITION_PERCENT") or "0.25"
    return Settings(
        trading_mode=_mode(),
        paper_starting_cash=float(os.getenv("PAPER_STARTING_CASH") or os.getenv("STAKE_USD") or 10),
        binance_api_key=(os.getenv("BINANCE_API_KEY") or "").strip().strip('"').strip("'"),
        binance_api_secret=(os.getenv("BINANCE_API_SECRET") or "").strip().strip('"').strip("'"),
        live_confirm=(os.getenv("BINANCE_LIVE_CONFIRM") or os.getenv("LIVE_TRADING_CONFIRM") or "").strip(),
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
        stake_usd=stake,
        goal_usd=float(os.getenv("GOAL_USD") or 50),
        min_notional=float(os.getenv("MIN_NOTIONAL") or 5),
        risk_per_trade=float(os.getenv("RISK_PER_TRADE") or 0.02),
        max_position_percent=float(os.getenv("MAX_POSITION_PERCENT") or max_pos_default),
        max_exposure=float(os.getenv("MAX_EXPOSURE") or 1.0),
        unprotected_policy=(os.getenv("UNPROTECTED_POLICY") or "flatten").strip().lower(),
    )


def missing_credentials(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    missing: list[str] = []
    if settings.trading_mode in {"testnet", "live"}:
        if not settings.binance_api_key:
            missing.append("BINANCE_API_KEY (or EXCHANGE_API_KEY)")
        if not settings.binance_api_secret:
            missing.append("BINANCE_API_SECRET (or EXCHANGE_API_SECRET)")
        if settings.trading_mode == "live" and not _live_confirm_ok():
            missing.append("BINANCE_LIVE_CONFIRM=I_UNDERSTAND (or LIVE_TRADING_CONFIRM=true)")
    return missing


def nvidia_key_present() -> bool:
    alias_secrets()
    return any(
        (os.getenv(name) or "").strip()
        for name in ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "NVAPI_KEY")
    )
