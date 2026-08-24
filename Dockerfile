FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
COPY assets ./assets
ENV HOST=0.0.0.0 PORT=8000 TRADING_MODE=paper
EXPOSE 8000
CMD ["python", "-m", "app"]
