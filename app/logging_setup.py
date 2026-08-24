"""File logs under logs/. Never print secrets."""

from __future__ import annotations

import logging
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
_SECRET = re.compile(r"(api[_-]?key|secret|bearer|sk-|sk_)[=:\s]+\S+", re.I)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET.sub("[redacted]", str(record.msg))
        if record.args:
            record.args = tuple(
                _SECRET.sub("[redacted]", str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return
    files = {
        "system": LOG_DIR / "system.log",
        "trading": LOG_DIR / "trading.log",
        "tradingagents": LOG_DIR / "tradingagents.log",
        "errors": LOG_DIR / "errors.log",
    }
    for name, path in files.items():
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(fmt)
        handler.addFilter(RedactFilter())
        if name == "errors":
            handler.setLevel(logging.ERROR)
            root.addHandler(handler)
        elif name == "tradingagents":
            logging.getLogger("tradingagents").addHandler(handler)
            logging.getLogger("tradingagents").propagate = True
        elif name == "trading":
            logging.getLogger("trading").addHandler(handler)
        else:
            root.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setLevel(logging.WARNING)
    stream.setFormatter(fmt)
    stream.addFilter(RedactFilter())
    root.addHandler(stream)


def tail_logs(n: int = 16) -> list[str]:
    path = LOG_DIR / "system.log"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]
