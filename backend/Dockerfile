# syntax=docker/dockerfile:1
# AI Personal CFO — backend service container.
#
# FastAPI server (uvicorn) on port 8000. Configuration comes from environment
# variables (see .env.example); user data lives in a SQLite file whose path is
# controlled by CFO_DB_PATH / CFO_DATA_DIR.
#
# Build:
#   docker build -t ai-cfo-backend -f backend/Dockerfile .
#
# Run (mount a volume at /var/data so data survives restarts):
#   docker run -p 8000:8000 -v cfo-data:/var/data ai-cfo-backend

FROM python:3.12.3-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime libs needed by the ingestion stack (pdfplumber, openpyxl, chromadb ONNX).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# Default data directory for the SQLite database. Mount a volume here in
# production (Coolify, Docker Compose) so accounts and statements survive deploys.
ENV CFO_DATA_DIR=/var/data

EXPOSE 8000

# Single worker: the app is async-first and uses one SQLite connection. Multiple
# workers would each open their own connection and contend on the write lock.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]