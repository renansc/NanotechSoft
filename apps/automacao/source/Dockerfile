FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 5000

CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=1", "--threads=4", "--access-logfile=-", "wsgi:app"]
