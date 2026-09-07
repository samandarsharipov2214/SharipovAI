# F08: pin base by immutable digest (readable tag + digest).
# Update only via intentional base-image bump with CI (see docs/deploy-reproducibility.md).
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# F08: deploy path uses exact pins from requirements.txt (no unbound pip upgrade).
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "dashboard:app", "--host", "0.0.0.0", "--port", "8000"]
