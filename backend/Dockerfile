FROM node:22-bookworm-slim AS chart-engines
WORKDIR /engines
COPY engines/package.json engines/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-fund --no-audit
COPY engines/*.mjs ./

FROM python:3.12-slim-bookworm

WORKDIR /app

COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY skills /skills
COPY --from=chart-engines /usr/local/bin/node /usr/local/bin/node
COPY --from=chart-engines /engines /engines

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
