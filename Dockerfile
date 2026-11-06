# Comproof: one image serving the API, the comparison engine and the web app.

# ---- build the web app
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/ ./
# Remove any node_modules that came with the source, then install fresh.
RUN rm -rf node_modules && npm install --no-audit --no-fund && npm run build

# ---- run the API and the engine
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend/dist \
    DATA_DIR=/data \
    OMP_THREAD_LIMIT=1
# Tesseract with English and Arabic, complex-script shaping, fonts for the reports, LibreOffice for Word files.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara libraqm0 \
      fonts-dejavu-core fonts-noto-core fonts-hosny-amiri \
      libreoffice-writer-nogui \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 comproof && mkdir -p /data && chown comproof /data
EXPOSE 8000
# Railway mounts its volume at /data owned by root (no Dockerfile VOLUME allowed): take ownership of the
# volume as root, then drop to the unprivileged comproof user for the server itself.
CMD ["sh", "-c", "mkdir -p \"${DATA_DIR:-/data}\" && chown comproof \"${DATA_DIR:-/data}\" && HOME=/home/comproof exec setpriv --reuid=comproof --regid=comproof --init-groups uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
