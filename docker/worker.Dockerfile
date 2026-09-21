FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

# Also used, via command override, for the recovery sweeper (src.worker.recovery_sweeper)
# and the one-shot migration step (alembic upgrade head) — see docker-compose.yml.
CMD ["python", "-m", "src.worker.worker"]
