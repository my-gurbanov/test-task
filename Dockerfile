FROM ghcr.io/astral-sh/uv:0.9.4 AS uv
FROM python:3.15-slim-trixie AS application

ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /srv/www

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked

COPY alembic.ini ./
COPY payment_processing ./payment_processing
COPY tests ./tests
USER 65534:65534
CMD ["python", "-m", "payment_processing.api.application"]
