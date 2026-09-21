# DSM-AE production image: queue WebUI + embedded benchmark worker
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DSM_AE_HOME=/app \
    DSM_AE_PUBLIC_BASE=/dsm-ae

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install package with LLM + web extras
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY taxonomy ./taxonomy
COPY diagnosis ./diagnosis
COPY metrics ./metrics
COPY sources ./sources
COPY docs ./docs
COPY treatment ./treatment
COPY harbor_tasks ./harbor_tasks
# composite_fixture seeds its workspace from this tree; without it the pack
# raises FileNotFoundError before any model call and takes the whole job with
# it (the worker does not retry on failure).
COPY fixtures ./fixtures
COPY models.yaml.example ./models.yaml.example

RUN pip install --upgrade pip \
 && pip install -e ".[llm,web]"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runtime dirs (compose mounts over these)
RUN mkdir -p /app/reports /app/data /app/logs /app/work

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${DSM_AE_PORT:-8765}/api/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
