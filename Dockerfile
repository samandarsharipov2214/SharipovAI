FROM python:3.12-slim

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="SharipovAI OS" \
      org.opencontainers.image.description="Safety-first AI trading operating system" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip check

COPY . .

RUN python -m compileall -q /app \
    && install -d -m 0750 /var/lib/sharipovai /var/log/sharipovai \
    && useradd --system --uid 10001 --create-home --home-dir /home/sharipovai sharipovai \
    && chown -R sharipovai:sharipovai /app /var/lib/sharipovai /var/log/sharipovai

USER sharipovai
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=45s --retries=5 \
  CMD curl --fail --silent --show-error --max-time 4 http://127.0.0.1:8000/health >/dev/null || exit 1

CMD ["uvicorn", "dashboard:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--timeout-keep-alive", "15"]
