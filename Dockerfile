# Multi-stage build pro backend + frontend

# Stage 1: Build frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm install
COPY ui/ ./
RUN npm run build

# Stage 2: Python backend + frontend
FROM python:3.11-slim
WORKDIR /app

# Instalace systémových závislostí
RUN apt-get update && apt-get install -y \
    curl \
    rsync \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Python závislosti
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopírování backend kódu
COPY backend/ ./backend/

# Kopírování zbuildovaného frontendu
COPY --from=frontend-builder /app/ui/dist ./static
# Kopírování obrázků workflow
COPY ui/images ./static/images
# Kopírování version.json
COPY ui/static/version.json ./static/version.json

# Exponování portu
EXPOSE 8000

# Spuštění aplikace
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

