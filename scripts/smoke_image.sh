#!/usr/bin/env bash
set -euo pipefail
scratch="$(mktemp -d -t maritime-smoke.XXXXXXXX)"
container=""
cleanup() {
  if [[ -n "$container" ]]; then docker stop -t 1 "$container" >/dev/null 2>&1 || true; fi
  local -a cleanup_python=(python3)
  # The Linux runner's rootful Docker writes files owned by root to the test bind mount.
  if [[ "${RUNNER_OS:-}" == Linux && "${GITHUB_ACTIONS:-}" == true ]]; then cleanup_python=(sudo -n python3); fi
  "${cleanup_python[@]}" -c 'import shutil, sys; from pathlib import Path; p = Path(sys.argv[1]); assert p.is_absolute() and p.name.startswith("maritime-smoke."); shutil.rmtree(p)' "$scratch"
}
trap cleanup EXIT
runtime="$scratch/data/aistudio2api/runtime"
mkdir -p "$runtime/camoufox"

pin() { sed -n "s/^ARG $1=//p" "$2/Dockerfile"; }
build() {
  # Do not inherit host-only Docker proxy defaults into the build.
  docker build --platform linux/amd64 \
    --build-arg HTTP_PROXY= --build-arg HTTPS_PROXY= --build-arg ALL_PROXY= \
    --build-arg http_proxy= --build-arg https_proxy= --build-arg all_proxy= \
    -t "$1" "$2"
}

smoke() {
  local image="$1" version="$2" browser="$3"
  container="$(docker run -d --rm --platform linux/amd64 --network none \
    -e PROXY_API_KEY=smoke-only -e LOG_FILE=false \
    -e WARM_WORKER_LIMIT=1 -e MAX_ACTIVE_WORKERS=1 \
    -e WARM_STARTUP_CONCURRENCY=1 -e PER_ACCOUNT_CONCURRENCY=1 \
    --mount "type=bind,source=$scratch/data,target=/data" "$image")"
  if ! docker exec -i "$container" python3 - "$version" "$browser" <<'PY'
import json, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

version, browser = sys.argv[1:]
for _ in range(40):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18789/api/status', timeout=2) as response:
            status = json.load(response)
        assert status['version'] == version, status['version']
        if status.get('camoufox', {}).get('ready'):
            break
    except (urllib.error.URLError, TimeoutError):
        pass
    time.sleep(1)
else:
    raise RuntimeError('entrypoint did not start AIStudio2API with a ready Camoufox cache')

dependencies = subprocess.check_output(['ldd', browser], text=True)
assert 'not found' not in dependencies, dependencies
with tempfile.TemporaryDirectory() as tmp:
    screenshot = Path(tmp) / 'page.png'
    subprocess.run([browser, '-headless', '-no-remote', '-profile', tmp,
                    '--screenshot', str(screenshot), 'data:text/html,<h1>Maritime smoke</h1>'],
                   check=True, timeout=60)
    assert screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), 'browser did not render the local page'
print(json.dumps({'version': version, 'browser': browser, 'offline_render': True}))
PY
  then
    docker logs "$container" || true
    return 1
  fi
  docker stop -t 1 "$container" >/dev/null
  container=""
}

build maritime-candidate .
docker image inspect maritime-candidate --format 'Image bytes: {{.Size}}'
browser_url="$(pin CAMOUFOX_URL .)"
old_url=""
if [[ "${1:-}" == --rollback ]]; then
  mkdir -p "$scratch/old"
  git archive "${2:-HEAD}" Dockerfile entrypoint.sh maritime_proxy.py scripts | tar -x -C "$scratch/old"
  old_url="$(pin CAMOUFOX_URL "$scratch/old")"
fi
if [[ -n "$old_url" && "$old_url" != "$browser_url" ]]; then
  old_sha="$(pin CAMOUFOX_SHA256 "$scratch/old")"
  # v0.3.6 predates the checksum pin; this is its official release asset digest.
  if [[ -z "$old_sha" ]]; then
    [[ "$(pin AISTUDIO_VERSION "$scratch/old")" == v0.3.6 ]]
    old_sha=1bea4b55a51c88e82dc7d426d9c75093d942d2afc8c911cb8fc78ebf723d686c
  fi
  docker run --rm --platform linux/amd64 -e "CAMOUFOX_URL=$old_url" -e "CAMOUFOX_SHA256=$old_sha" \
    --mount "type=bind,source=$scratch/data,target=/data" -w /data/aistudio2api \
    --entrypoint python3 maritime-candidate /app/prepare_camoufox.py
  old_version="${old_url%/*}"
  old_version="${old_version##*/v}"
  old_cache="camoufox-$old_version-$old_sha"
  if [[ ! -f "$scratch/old/scripts/prepare_camoufox.py" ]]; then
    rmdir "$runtime/camoufox"
    mv "$runtime/$old_cache" "$runtime/camoufox"
    old_cache=camoufox
  fi
  old_fingerprint="$(sha256sum "$runtime/$old_cache/"{application.ini,camoufox-bin,libxul.so})"
fi

# Download and install through the same helper used in the image, before offline startup.
docker run --rm --platform linux/amd64 \
  --mount "type=bind,source=$scratch/data,target=/data" -w /data/aistudio2api \
  --entrypoint python3 maritime-candidate /app/prepare_camoufox.py
browser="$(docker run --rm --platform linux/amd64 --network none \
  --mount "type=bind,source=$scratch/data,target=/data" -w /data/aistudio2api \
  --entrypoint python3 maritime-candidate /app/prepare_camoufox.py --path)"
smoke maritime-candidate "$(pin AISTUDIO_VERSION .)" "$browser"

if [[ -n "$old_url" && "$old_url" != "$browser_url" ]]; then
  old_browser="/data/aistudio2api/runtime/$old_cache/camoufox-bin"
  [[ "$browser" != "$old_browser" ]]
  build maritime-rollback "$scratch/old"
  smoke maritime-rollback "$(pin AISTUDIO_VERSION "$scratch/old")" "$old_browser"
  [[ "$(sha256sum "$runtime/$old_cache/"{application.ini,camoufox-bin,libxul.so})" == "$old_fingerprint" ]]
  echo 'Rollback browser cache unchanged'
fi
