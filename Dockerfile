FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY binance_agent ./binance_agent
COPY static ./static
COPY index.html ./index.html
RUN pip install ".[ai]"

RUN useradd --create-home --uid 10001 agent && mkdir -p /app/data && chown -R agent:agent /app
USER agent

EXPOSE 8000
CMD ["uvicorn", "binance_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
