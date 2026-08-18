.PHONY: install install-ai run test lint

install:
	python -m pip install -e ".[dev]"

install-ai:
	python -m pip install -e ".[ai,dev]"

run:
	uvicorn binance_agent.app:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest

lint:
	ruff check .
