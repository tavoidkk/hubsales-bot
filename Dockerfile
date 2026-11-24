# HubSales Group — bot de reclutamiento
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias primero: se cachea la capa mientras no cambie requirements.txt.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY config ./config
COPY scripts ./scripts

# El .env NO se copia: se inyecta en runtime (Coolify / docker compose).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/', timeout=4).read()" || exit 1

# Coolify inyecta PORT; si no viene, usamos 8000.
ENV PORT=8000
CMD sh -c 'uvicorn agent.main:app --host 0.0.0.0 --port "$PORT"'
