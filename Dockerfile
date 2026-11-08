# Fallback build for Railway when Railpack can't run (2026-11-08: GitHub release downloads
# returned 504, and Railpack fetches mise and Python from GitHub releases). This image needs
# only Docker Hub (python base image) and PyPI (requirements.txt).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# The server reads these relative to the repo root: backend code, the records index
# (data/records.sqlite) and the mock-mode fixtures.
COPY backend ./backend
COPY data/records.sqlite ./data/records.sqlite
COPY fixtures ./fixtures

# Shell form so ${PORT} (set by Railway) expands.
CMD uvicorn server.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}
