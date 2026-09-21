FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

WORKDIR /app
# Pack-specific fixtures only (gold files, contracts, seeds etc). No full dsm_ae src tree here.
COPY harbor_tasks/dsm-ae/tool_integrity/environment/fixtures/ /app/

# Ensure logs dir for verifier output (harbor verifier will exec tests/test.sh)
RUN mkdir -p /logs/verifier

# No default CMD; Harbor orchestrates agent phase then verifier/tests/test.sh