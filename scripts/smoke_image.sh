#!/usr/bin/env bash
set -euo pipefail
# Do not inherit host-only Docker proxy defaults into the build.
docker build --platform linux/amd64 \
  --build-arg HTTP_PROXY= --build-arg HTTPS_PROXY= --build-arg ALL_PROXY= \
  --build-arg http_proxy= --build-arg https_proxy= --build-arg all_proxy= \
  -t maritime-candidate .
version="$(sed -n 's/^ARG AISTUDIO_VERSION=//p' Dockerfile)"
docker run --rm --platform linux/amd64 --network none --memory 384m --cpus 1 --pids-limit 96 \
  -e "EXPECTED_VERSION=$version" -e LISTEN_ADDR=127.0.0.1:18790 \
  -e PROXY_API_KEY=smoke-only -e LOG_FILE=false \
  -e WARM_WORKER_LIMIT=1 -e MAX_ACTIVE_WORKERS=1 \
  -e WARM_STARTUP_CONCURRENCY=1 -e PER_ACCOUNT_CONCURRENCY=1 \
  --entrypoint python3 maritime-candidate -c '
import json, os, subprocess, time, urllib.error, urllib.request
dependencies = subprocess.run(["ldd", "/app/runtime/camoufox/camoufox-bin"], capture_output=True, text=True, check=True)
assert "not found" not in dependencies.stdout, "missing browser dependencies"
child = subprocess.Popen(["/app/aistudio2api", "--open-ui=false"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for attempt in range(30):
        if child.poll() is not None:
            raise RuntimeError("binary exited before readiness")
        try:
            with urllib.request.urlopen("http://127.0.0.1:18790/api/status", timeout=2) as response:
                status = json.load(response)
            assert status["version"] == os.environ["EXPECTED_VERSION"]
            print(json.dumps({"version": status["version"], "browser_dependencies": "ok"}))
            break
        except urllib.error.URLError:
            time.sleep(1)
    else:
        raise RuntimeError("binary status endpoint timed out")
finally:
    child.terminate()
    child.wait(timeout=10)
'
