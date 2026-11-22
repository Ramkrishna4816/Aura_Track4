FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AURA_WEIGHTS_DIR=/app/weights

COPY requirements.txt run.sh ./
COPY code/ ./code/

RUN --mount=type=secret,id=proxy_ca \
    set -eu; \
    chmod -R a+rX code; \
    chmod a+rx run.sh; \
    mkdir -p weights outputs; \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt

ENTRYPOINT ["./run.sh"]
