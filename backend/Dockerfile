# Backend dashboard + ffprobe. Untuk DEV di laptop (x86) maupun build di Jetson.
# Catatan Jetson: untuk transcode hardware, ffmpeg di image ini HARUS diganti
# jetson-ffmpeg (nvmpi). Untuk dev/COPY di laptop, ffmpeg distro sudah cukup.
FROM python:3.12-slim

# ffmpeg menyediakan ffprobe (deteksi codec) — wajib untuk mode auto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend ./frontend

ENV FRONTEND_DIR=/app/frontend \
    DB_PATH=/app/data/gateway.db \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
