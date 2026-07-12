FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY server/pyproject.toml server/uv.lock* ./server/
RUN cd server && uv sync --frozen --no-dev 2>/dev/null || cd server && uv sync --no-dev

COPY server/ ./server/
COPY doc/ ./doc/

ENV DATABASE_PATH=/data/stock_analysis.db \
    LOG_DIR=/data/logs \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

RUN mkdir -p /data/logs

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/api/health', timeout=3)" || exit 1

WORKDIR /app/server
CMD ["uv", "run", "python", "main.py", "--serve-only", "--host", "0.0.0.0", "--port", "8100"]
