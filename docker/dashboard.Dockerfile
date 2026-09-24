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

# The project itself: seconds, since every dependency is already installed.
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "src/ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
