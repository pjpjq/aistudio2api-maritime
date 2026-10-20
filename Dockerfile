FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcairo2 libdbus-1-3 libdbus-glib-1-2 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 libxss1 \
    libxt6 libxtst6 libegl1 libegl-mesa0 libgl1-mesa-dri xvfb python3 curl unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ARG AISTUDIO_VERSION=v0.2.13
ARG AISTUDIO_SHA256=31c5b16e5a2e84e932dcbc13364f04e58b7bd0c6a699cc1465c5d7443d4e6e51
RUN curl -L --fail --retry 3 --retry-delay 2 \
      -o /tmp/aistudio2api.tar.gz \
      "https://github.com/Mag1cFall/AIStudio2API/releases/download/$AISTUDIO_VERSION/aistudio2api-$AISTUDIO_VERSION-linux-amd64.tar.gz" \
    && echo "$AISTUDIO_SHA256  /tmp/aistudio2api.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/aistudio2api.tar.gz -C /app --strip-components=1 "aistudio2api-$AISTUDIO_VERSION-linux-amd64/aistudio2api" \
    && rm -f /tmp/aistudio2api.tar.gz
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
