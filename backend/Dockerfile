# syntax=docker/dockerfile:1

FROM python:3.12-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install build dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libffi-dev \
    libmagic1 \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    pkg-config \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt

RUN python -m venv /opt/venv \
 && . /opt/venv/bin/activate \
 && pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    GUNICORN_WORKERS=2 \
    GUNICORN_TIMEOUT=600 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json \
    LOG_COLOR=off \
    LOG_REQUEST_SLOW_MS=1500 \
    LOG_SQLALCHEMY_LEVEL=WARNING \
    HOST=0.0.0.0 \
    PORT=8000

# Install runtime dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    libmagic1 \
    libpq5 \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app

COPY . ./backend
RUN chmod +x /app/backend/docker-entrypoint.sh

EXPOSE 8000

CMD ["/app/backend/docker-entrypoint.sh"]
