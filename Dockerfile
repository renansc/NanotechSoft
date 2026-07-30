FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg openssh-client tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5600

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5600} --workers 1 --threads 16 --timeout 240 app:app"]
