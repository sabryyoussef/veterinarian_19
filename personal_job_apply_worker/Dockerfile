FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JOB_APPLY_ARTIFACTS_DIR=/artifacts \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY app ./app
COPY fixtures ./fixtures
COPY tests ./tests

RUN mkdir -p /artifacts && chmod 0700 /artifacts

EXPOSE 8095

# Dedicated service — do NOT reuse firefox-whatsapp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8095"]
