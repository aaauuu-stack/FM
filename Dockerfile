FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8765

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data

# web only — scrape (curl_cffi) optional and can fail on slim images
RUN pip install --no-cache-dir ".[web]"

EXPOSE 8765

CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8765}"]
