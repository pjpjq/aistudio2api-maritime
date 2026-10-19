"""Pin verified stable releases; fail closed rather than guess a new release format."""

import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


OFFICIAL = 'Mag1cFall/AIStudio2API'
VERSION = r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'


def version_tuple(value):
    match = re.fullmatch(VERSION, str(value))
    if not match:
        raise RuntimeError('invalid stable release version')
    return tuple(map(int, match.groups()))


def fetch(url):
    headers = {'User-Agent': 'maritime-upstream-sync'}
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if url.startswith('https://api.github.com/') and token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'upstream metadata HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('upstream metadata network failure') from None
    if len(raw) > 2 * 1024 * 1024:
        raise RuntimeError('upstream metadata exceeds size limit')
    return raw.decode('utf-8')


def emit(values):
    values = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in values.items()}
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                output.write(f'{key}={value}\n')
    print(json.dumps(values))


def check():
    dockerfile = Path('Dockerfile')
    source = dockerfile.read_text()
    pins = {}
    for name in ('VERSION', 'SHA256'):
        lines = re.findall(rf'(?m)^ARG AISTUDIO_{name}=(.*)$', source)
        if len(lines) != 1:
            raise RuntimeError('Dockerfile must have exactly one version/checksum pin')
        pins[name] = lines[0]
    previous = pins['VERSION']
    version_tuple(previous)
    if not re.fullmatch(r'[0-9a-f]{64}', pins['SHA256']):
        raise RuntimeError('invalid current SHA-256 pin')
    release = json.loads(fetch(f'https://api.github.com/repos/{OFFICIAL}/releases/latest'))
    if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise RuntimeError('latest release must be stable and published')
    version = release.get('tag_name')
    if version_tuple(version) < version_tuple(previous):
        raise RuntimeError('refusing upstream version downgrade')
    filename = f'aistudio2api-{version}-linux-amd64.tar.gz'
    assets = release.get('assets', [])
    if not isinstance(assets, list):
        raise RuntimeError('invalid release assets')
    assets = [asset for asset in assets if isinstance(asset, dict) and asset.get('name') == filename]
    expected_url = f'https://github.com/{OFFICIAL}/releases/download/{version}/{filename}'
    if len(assets) != 1 or assets[0].get('browser_download_url') != expected_url:
        raise RuntimeError('missing or untrusted Linux amd64 release asset')
    digest = assets[0].get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise RuntimeError('missing or invalid official asset SHA-256 digest')
    checksum = digest.removeprefix('sha256:')
    changed = version != previous
    if not changed and checksum != pins['SHA256']:
        raise RuntimeError('same-version asset changed; manual review required')
    if changed:
        browser = re.findall(r'https://github\.com/daijro/camoufox/releases/download/v([^/]+)/camoufox-', source)
        upstream_source = fetch(f'https://raw.githubusercontent.com/{OFFICIAL}/{version}/internal/camoufoxnative/download.go')
        required_browser = re.findall(r'(?m)^const camoufoxRelease = "([^"]+)"', upstream_source)
        if len(browser) != 1 or required_browser != browser:
            raise RuntimeError('Camoufox compatibility changed; update image manually')
        source = source.replace(f'ARG AISTUDIO_VERSION={previous}\n', f'ARG AISTUDIO_VERSION={version}\n')
        source = source.replace(f'ARG AISTUDIO_SHA256={pins["SHA256"]}\n', f'ARG AISTUDIO_SHA256={checksum}\n')
        dockerfile.write_text(source)
    emit({'changed': changed, 'version': version, 'previous_version': previous})


def gate(state, force):
    now = time.time()
    last = float(state.read_text()) if state.exists() else 0
    if not math.isfinite(last) or last < 0 or last > now:
        raise RuntimeError('invalid or future successful-check timestamp')
    emit({'due': force or now - last >= 18000})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'gate', 'record'))
    parser.add_argument('--state-path', type=Path, default=Path('.upstream-check-state'))
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.command == 'check':
        check()
    elif args.command == 'gate':
        gate(args.state_path, args.force)
    else:
        args.state_path.write_text(str(time.time()))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from None
