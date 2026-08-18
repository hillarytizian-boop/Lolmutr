"""Lightweight OpenAI-compatible client for Termux — no LangChain required.

Used to let the Portfolio Manager re-rate a finished native-desk book when
an LLM key is present. Failures fall back to the heuristic rating.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from app.models import RATINGS, Decision, rating_to_action

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "base": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    "openrouter": {
        "base": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "model": "openai/gpt-4o-mini",
    },
    "groq": {
        "base": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
    },
    "deepseek": {
        "base": "https://api.deepseek.com",
        "env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "xai": {
        "base": "https://api.x.ai/v1",
        "env": "XAI_API_KEY",
        "model": "grok-2-latest",
    },
    "nvidia": {
        "base": "https://integrate.api.nvidia.com/v1",
        "env": "NVIDIA_API_KEY",
        "model": "z-ai/glm-5.2",
    },
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env": "GOOGLE_API_KEY",
        "model": "gemini-2.0-flash",
    },
}

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def detect_provider() -> str | None:
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if (os.getenv("NVIDIA_API_KEY") or os.getenv("NVIDIA_NIM_API_KEY") or os.getenv("NVAPI_KEY")) and (
        not explicit or explicit in {"nvidia", "openai_compatible"}
    ):
        return "nvidia"
    if explicit in PROVIDERS and os.getenv(PROVIDERS[explicit]["env"]):
        return explicit
    for name, spec in PROVIDERS.items():
        if os.getenv(spec["env"]):
            return name
    return None


def llm_key_present() -> bool:
    names = (
        "NVIDIA_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVAPI_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
    )
    return any((os.getenv(n) or "").strip() for n in names)


def resolve_endpoint() -> tuple[str, str, str] | None:
    """Return (base_url, api_key, model) or None."""
    name = detect_provider()
    if not name:
        return None
    spec = PROVIDERS[name]
    key = (
        os.getenv(spec["env"])
        or os.getenv("NVIDIA_API_KEY")
        or os.getenv("NVIDIA_NIM_API_KEY")
        or os.getenv("NVAPI_KEY")
        or ""
    ).strip()
    if not key:
        return None
    base = (os.getenv("LLM_BASE_URL") or spec["base"]).rstrip("/")
    model = (os.getenv("LLM_MODEL") or spec["model"]).strip()
    return base, key, model


def parse_llm_rating(text: str) -> dict[str, Any] | None:
    """Extract a 5-tier rating payload from model text."""
    if not text:
        return None
    blob = text.strip()
    match = _JSON_RE.search(blob)
    if match:
        blob = match.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = None
    rating = None
    thesis = ""
    confidence = None
    if isinstance(data, dict):
        rating = str(data.get("rating") or data.get("Rating") or "").strip()
        thesis = str(data.get("thesis") or data.get("summary") or "").strip()
        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
    if not rating:
        for line in text.splitlines():
            low = line.lower()
            if "rating" in low:
                for name in RATINGS:
                    if name.lower() in low:
                        rating = name
                        break
    if not rating:
        return None
    # Title-case against the canonical list.
    canon = {r.lower(): r for r in RATINGS}
    rating = canon.get(rating.lower())
    if not rating:
        return None
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    return {"rating": rating, "thesis": thesis, "confidence": confidence}


def complete(system: str, user: str, timeout: float = 90.0) -> str | None:
    endpoint = resolve_endpoint()
    if not endpoint:
        return None
    base, key, model = endpoint
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"].get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
                else:
                    parts.append(str(part))
            return "".join(parts) or None
        return content
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def overlay_decision(
    decision: Decision,
    reports: list[Any],
    symbol: str,
    price: float,
    vol_mult: float,
    memory: list[str] | None = None,
    small_account: bool = False,
) -> Decision:
    """TradingAgents PM overlay: maximize risk-adjusted profit. Fail-open."""
    if not llm_configured():
        return decision
    brief = []
    for report in reports:
        if hasattr(report, "name"):
            brief.append(f"- {report.name} [{report.stance} {report.score:+.2f}]: {report.summary}")
        elif isinstance(report, dict):
            brief.append(
                f"- {report.get('name')} [{report.get('stance')}]: {report.get('summary')}"
            )
    lessons = "\n".join(f"- {row}" for row in (memory or [])[-8:]) or "- none yet"
    user = (
        f"Symbol {symbol} last {price}. Heuristic rating {decision.rating} "
        f"(score {decision.score:+.2f}, stop {decision.stop_loss}, "
        f"target {decision.take_profit}).\n"
        f"Analyst book:\n" + "\n".join(brief) + "\n\n"
        f"Recent closed trades (learn what paid):\n{lessons}\n\n"
        "Reply with JSON only: "
        '{"rating":"Buy|Overweight|Hold|Underweight|Sell","confidence":0.0,'
        '"thesis":"two sentences"}'
    )
    text = complete(
        "You are the TradingAgents Portfolio Manager on a Binance spot desk. "
        "Mandate: compound a small USDT stake toward a 5x goal. "
        "Take clean Buys only when the book agrees; cut losers; let winners "
        "run for the trail. Never invent prices. Never ignore a stop.",
        user,
    )
    parsed = parse_llm_rating(text or "")
    if not parsed:
        return decision
    from app.profit import profit_size_pct

    decision.rating = parsed["rating"]
    decision.action = rating_to_action(decision.rating)
    if parsed.get("confidence") is not None:
        decision.confidence = parsed["confidence"]
    decision.size_pct = profit_size_pct(
        decision.rating, decision.confidence, vol_mult, small_account=small_account
    )
    if parsed.get("thesis"):
        decision.thesis = parsed["thesis"]
        decision.executive_summary = parsed["thesis"][:240]
    decision.engine = "trading-agent"
    return decision
