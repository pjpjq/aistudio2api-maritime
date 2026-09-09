#!/bin/sh
set -eu
mkdir -p "${AISTUDIO_AUTH_STATES:-/data/auth}"
export AISTUDIO_AUTH_STATES="${AISTUDIO_AUTH_STATES:-/data/auth}"
export LISTEN_ADDR="127.0.0.1:18790"
/app/aistudio2api --open-ui=false &
child=$!
trap 'kill "$child" 2>/dev/null || true' TERM INT EXIT
(
    for _ in $(seq 1 60); do
        if curl -fsS -X POST http://127.0.0.1:18790/api/control/start >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
) &
exec python3 /app/maritime_proxy.py "$child"
