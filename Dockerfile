FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcairo2 libdbus-1-3 libdbus-glib-1-2 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 libxss1 \
    libxt6 curl unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY aistudio2api-linux-amd64 /app/aistudio2api
COPY entrypoint.sh /app/entrypoint.sh
COPY maritime_proxy.py /app/maritime_proxy.py
RUN set -eux; \
    mkdir -p /app/runtime/camoufox /data/auth; \
    curl -L --fail --retry 3 --retry-delay 2 \
      -o /tmp/camoufox.zip \
      https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-lin.x86_64.zip; \
    unzip -q /tmp/camoufox.zip -d /app/runtime/camoufox; \
    chmod 755 /app/entrypoint.sh /app/aistudio2api /app/runtime/camoufox/camoufox-bin; \
    rm -f /tmp/camoufox.zip
ENV AISTUDIO_AUTH_STATES=/data/auth
ENTRYPOINT ["/app/entrypoint.sh"]
