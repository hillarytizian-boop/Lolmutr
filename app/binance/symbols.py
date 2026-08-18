"""Translate between Binance spot pairs and TradingAgents / Yahoo tickers.

TradingAgents crypto mode expects ``BTC-USD``. Binance spot uses ``BTCUSDT``.
Keep the mapping syntactic so every call site agrees.
"""

from __future__ import annotations

import re

_PAIR = re.compile(r"^[A-Z0-9]{4,20}$")
_YAHOO = re.compile(r"^[A-Z0-9]+-(USD|USDT|USDC)$")

# Longest-first so USDT / USDC win over USD.
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD", "BTC", "ETH", "BNB")

# Bases Yahoo (and therefore TradingAgents) already knows how to price.
_YAHOO_CRYPTO = {
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "LTC",
    "BCH",
    "DOT",
    "AVAX",
    "LINK",
    "BNB",
    "MATIC",
    "ATOM",
    "UNI",
    "NEAR",
    "APT",
    "SUI",
    "PEPE",
    "SHIB",
    "TRX",
    "TON",
    "FIL",
    "ARB",
    "OP",
}


def normalize_pair(raw: str) -> str:
    """Accept ``btcusdt``, ``BTC-USD``, ``BTC/USDT`` and return ``BTCUSDT``."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("symbol is required")
    compact = (
        raw.strip()
        .upper()
        .replace("-", "")
        .replace("/", "")
        .replace("_", "")
        .replace(" ", "")
    )
    if compact.endswith("USD") and not compact.endswith(("USDT", "USDC")):
        compact = compact[:-3] + "USDT"
    if not _PAIR.fullmatch(compact):
        raise ValueError(f"invalid symbol: {raw!r}")
    return compact


def split_pair(symbol: str) -> tuple[str, str]:
    pair = normalize_pair(symbol)
    for quote in _QUOTES:
        if pair.endswith(quote) and len(pair) > len(quote):
            return pair[: -len(quote)], quote
    raise ValueError(f"cannot split symbol: {symbol!r}")


def to_binance(raw: str) -> str:
    return normalize_pair(raw)


def to_yahoo(raw: str) -> str:
    """``BTCUSDT`` / ``BTC-USD`` → ``BTC-USD`` for TradingAgents crypto mode."""
    text = raw.strip().upper()
    if _YAHOO.fullmatch(text):
        base = text.split("-", 1)[0]
        return f"{base}-USD"
    base, _quote = split_pair(text)
    return f"{base}-USD"


def from_yahoo(ticker: str) -> str:
    """``BTC-USD`` → ``BTCUSDT`` (Binance's default stable quote)."""
    text = ticker.strip().upper()
    if "-" in text:
        base, quote = text.split("-", 1)
        if quote in ("USD", "USDT", "USDC"):
            return f"{base}USDT"
    return normalize_pair(text)


def is_known_crypto(raw: str) -> bool:
    try:
        base, _ = split_pair(raw)
    except ValueError:
        text = raw.strip().upper()
        if "-" in text:
            base = text.split("-", 1)[0]
        else:
            return False
    return base in _YAHOO_CRYPTO
