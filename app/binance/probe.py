"""Talk to Binance for real. Never print secrets."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx

HOSTS = (
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://data-api.binance.vision",
)
TESTNET = "https://testnet.binance.vision"
_TIMEOUT = 12.0
_UA = {"User-Agent": "LolmutrDesk/1.0"}


class ProbeError(RuntimeError):
    pass


def _clean(value: str) -> str:
    return (value or "").strip().strip('"').strip("'")


def _get(base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    response = httpx.get(
        f"{base.rstrip('/')}{path}",
        params=params,
        headers=_UA,
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    if response.status_code >= 400:
        raise ProbeError(f"{response.status_code} {response.text[:180]}")
    return response.json()


def public_ok(base: str) -> tuple[bool, str]:
    try:
        _get(base, "/api/v3/ping")
        px = _get(base, "/api/v3/ticker/price", {"symbol": "BTCUSDT"})
        return True, f"ok last={px.get('price')}"
    except Exception as exc:
        return False, str(exc)[:180]


def pick_public_host() -> tuple[str | None, str]:
    errors = []
    for host in HOSTS:
        ok, detail = public_ok(host)
        if ok:
            return host, detail
        errors.append(f"{host}: {detail}")
    return None, " | ".join(errors)


def server_time(base: str) -> int:
    data = _get(base, "/api/v3/time")
    return int(data["serverTime"])


def signed_account(base: str, api_key: str, api_secret: str) -> tuple[bool, str, dict[str, Any]]:
    key = _clean(api_key)
    secret = _clean(api_secret)
    if not key or not secret:
        return False, "missing BINANCE_API_KEY or BINANCE_API_SECRET", {}
    try:
        ts = server_time(base)
    except Exception:
        ts = int(time.time() * 1000)
    params = {"timestamp": ts, "recvWindow": 60000}
    query = urlencode(params)
    sig = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base.rstrip('/')}/api/v3/account?{query}&signature={sig}"
    headers = {**_UA, "X-MBX-APIKEY": key}
    try:
        response = httpx.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        return False, f"network {exc}", {}
    if response.status_code >= 400:
        body = response.text[:220]
        return False, f"{response.status_code} {body}", {}
    data = response.json()
    usdt = 0.0
    for bal in data.get("balances") or []:
        if bal.get("asset") == "USDT":
            usdt = float(bal.get("free") or 0) + float(bal.get("locked") or 0)
            break
    return True, f"account ok USDT={usdt:.4f}", data


def probe(api_key: str = "", api_secret: str = "", *, testnet: bool = False) -> dict[str, Any]:
    if testnet:
        host, pub = (TESTNET, "")[0], ""
        ok, pub = public_ok(TESTNET)
        host = TESTNET if ok else None
    else:
        host, pub = pick_public_host()
    result: dict[str, Any] = {
        "public_ok": bool(host),
        "public_host": host,
        "public_detail": pub,
        "signed_ok": False,
        "signed_detail": "keys not checked",
    }
    if api_key and api_secret:
        bases = []
        if host:
            bases.append(host)
        bases.extend([TESTNET] if testnet else list(HOSTS))
        last_detail = "unsigned"
        for base in bases:
            ok, detail, data = signed_account(base, api_key, api_secret)
            last_detail = detail
            if ok:
                result["signed_ok"] = True
                result["signed_detail"] = detail
                result["public_host"] = base
                result["public_ok"] = True
                usdt = 0.0
                for bal in data.get("balances") or []:
                    if bal.get("asset") == "USDT":
                        usdt = float(bal.get("free") or 0)
                        break
                result["usdt_free"] = usdt
                break
        else:
            result["signed_ok"] = False
            result["signed_detail"] = last_detail
    return result
