FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl cups-client ffmpeg iputils-ping openssh-client poppler-utils snmp tesseract-ocr tesseract-ocr-por libcups2 libcups2-dev gcc \
    && pip install -r requirements.txt \
    && apt-get purge -y --auto-remove libcups2-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 5600

CMD ["sh", "-c", "export CHAMADOS_AGENDA_AUTOSTART=1; exec gunicorn --bind 0.0.0.0:${PORT:-5600} --workers 1 --threads 16 --timeout 240 app:app"]
