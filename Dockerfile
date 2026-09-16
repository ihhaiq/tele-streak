FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unprivileged; data/ must stay writable for the SQLite file.
RUN useradd --create-home --uid 10001 streak \
    && mkdir -p data \
    && chown -R streak:streak /app
USER streak

CMD ["python", "-m", "app.main"]
