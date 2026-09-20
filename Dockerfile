FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        ffmpeg \
        libraqm0 \
        gosu \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway volumes are mounted after the image is built and can be owned by
# root. The entrypoint fixes their ownership before dropping privileges.
RUN useradd --create-home --uid 10001 streak \
    && mkdir -p /app/data /data \
    && chown -R streak:streak /app /data \
    && install -m 0755 /app/docker-entrypoint.sh /usr/local/bin/streak-entrypoint

ENTRYPOINT ["/usr/local/bin/streak-entrypoint"]
CMD ["python", "-m", "app.main"]
