FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY skills /skills

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
