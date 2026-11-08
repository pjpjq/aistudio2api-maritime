FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcairo2 libdbus-1-3 libdbus-glib-1-2 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 libxss1 \
    libxt6 libxtst6 libegl1 libegl-mesa0 libgl1-mesa-dri xvfb python3 curl unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ARG AISTUDIO_VERSION=v0.3.3
ARG AISTUDIO_SHA256=80caf7c7ab5c52d7c8d453e2be4b130d4b40863b283929596a5dafa2e9e5923d
ARG CAMOUFOX_URL=https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-lin.x86_64.zip
RUN curl -L --fail --retry 3 --retry-delay 2 \
      -o /tmp/aistudio2api.tar.gz \
      "https://github.com/Mag1cFall/AIStudio2API/releases/download/$AISTUDIO_VERSION/aistudio2api-$AISTUDIO_VERSION-linux-amd64.tar.gz" \
    && echo "$AISTUDIO_SHA256  /tmp/aistudio2api.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/aistudio2api.tar.gz -C /app --strip-components=1 "aistudio2api-$AISTUDIO_VERSION-linux-amd64/aistudio2api" \
    && rm -f /tmp/aistudio2api.tar.gz
COPY entrypoint.sh /app/entrypoint.sh
COPY maritime_proxy.py /app/maritime_proxy.py
RUN set -eux; \
    mkdir -p /app/runtime /data/auth; \
    ln -s /data/aistudio2api/runtime/camoufox /app/runtime/camoufox; \
    chmod 755 /app/entrypoint.sh /app/aistudio2api
ENV AISTUDIO_AUTH_STATES=/data/auth
ENTRYPOINT ["/app/entrypoint.sh"]
