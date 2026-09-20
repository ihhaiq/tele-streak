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
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG BGUTIL_VERSION=1.3.1
RUN git clone --depth 1 --branch "$BGUTIL_VERSION" \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
        /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && deno install --allow-scripts=npm:canvas --frozen \
    && rm -rf /opt/bgutil-ytdlp-pot-provider/.git

COPY . .

# Railway volumes are mounted after the image is built and can be owned by
# root. The entrypoint fixes their ownership before dropping privileges.
RUN useradd --create-home --uid 10001 streak \
    && mkdir -p /app/data /data \
    && chown -R streak:streak /app /data \
    && install -m 0755 /app/docker-entrypoint.sh /usr/local/bin/streak-entrypoint

ENTRYPOINT ["/usr/local/bin/streak-entrypoint"]
CMD ["python", "-m", "app.main"]
