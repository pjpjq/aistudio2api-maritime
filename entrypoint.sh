#!/bin/sh
set -eu
mkdir -p "${AISTUDIO_AUTH_STATES:-/data/auth}"
export AISTUDIO_AUTH_STATES="${AISTUDIO_AUTH_STATES:-/data/auth}"
export LISTEN_ADDR="127.0.0.1:18790"
mkdir -p /data/aistudio2api/runtime
if [ ! -e /data/aistudio2api/runtime/camoufox ]; then
    ln -s /app/runtime/camoufox /data/aistudio2api/runtime/camoufox
fi
cd /data/aistudio2api
/app/aistudio2api --open-ui=false &
child=$!
trap 'kill "$child" 2>/dev/null || true' TERM INT EXIT
python3 - <<'PY' &
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request

base = "http://127.0.0.1:18790"
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
)
for _ in range(60):
    try:
        if os.environ.get("ADMIN_AUTH_ENABLED", "false").lower() == "true":
            body = json.dumps({"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]}).encode()
            request = urllib.request.Request(base + "/api/auth/login", data=body, headers={"Content-Type": "application/json"})
            with opener.open(request, timeout=5):
                pass
        with opener.open(urllib.request.Request(base + "/api/control/start", data=b"{}"), timeout=5):
            break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(1)
else:
    raise SystemExit("AIStudio2API did not accept the startup request")
PY
exec python3 /app/maritime_proxy.py "$child"
