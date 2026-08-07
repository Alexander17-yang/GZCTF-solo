FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 10001 arena && \
    useradd --system --uid 10001 --gid arena --home /app arena

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=arena:arena app ./app
RUN mkdir -p /data && chown arena:arena /data

USER arena

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
