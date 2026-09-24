FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Dependencies first, in their own layer keyed only on pyproject.toml, so a code
# or README change reuses it instead of rerunning the full install (~5 min).
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir hatchling -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && useradd --create-home --shell /bin/bash appuser

COPY README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
# One-shot data jobs (seed_orders, ingest_knowledge_base) and the policy they ingest.
COPY scripts ./scripts
COPY docs/policies ./docs/policies

# The project itself: seconds, since every dependency is already installed.
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && chown -R appuser:appuser /app

USER appuser

# Also used, via command override, for the recovery sweeper (src.worker.recovery_sweeper)
# and the one-shot migration step (alembic upgrade head) — see docker-compose.yml.
CMD ["python", "-m", "src.worker.worker"]
