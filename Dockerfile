# Sync Orchestrator — FastAPI + Jinja2 + HTMX + SQLite
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=Europe/Prague

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt


# --- testy: pytest + rsync (vygenerovaný skript se ověřuje skutečným během) ---
#   docker build --target test -t sync-orchestrator-test . && docker run --rm sync-orchestrator-test
FROM base AS test
RUN apt-get update && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt /app/
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app /app/app
COPY tests /app/tests
# Testy běží jako běžný uživatel — jinak by root přečetl i „nečitelnou“ složku.
RUN useradd -u 1000 -m tester
USER tester
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


# --- produkce (výchozí cíl buildu) ---
FROM base AS runtime

# Non-root uživatel (UID 1000) — na hostiteli: chown -R 1000:1000 ./data
RUN useradd -u 1000 -ms /bin/bash appuser && mkdir -p /data && chown appuser:appuser /data

COPY app /app/app
RUN chmod -R a+rX /app/app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:8000/health || exit 1

# Jeden worker: stav běžících skenů je v paměti procesu.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
