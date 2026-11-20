"""Deploy main and verify the public schema regression without exporting runtime secrets."""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


API = 'https://api.maritime.sh'
AGENT = '91a5b393-da23-430e-b333-8ed1b9d3408f'
REPO = 'https://github.com/pjpjq/aistudio2api-maritime.git'
BASELINE = Path('.deployment-baseline.json')
STARTED = Path('.deployment-started')
TERMINAL = {'success', 'failed', 'error', 'cancelled', 'canceled'}
MODELS = ('gemini-3.8-flash', 'gemini-4-argon')
PROBE_ERRORS = {'runtime_key', 'admin_login', 'admin_status', 'admin_logout', 'readiness',
                'http', 'transport', 'invalid_response', 'marker'}
CAPACITY_HEADROOM_KIB = 64 * 1024

PROBE = r'''import hashlib, http.cookiejar, json, urllib.error, urllib.request
from pathlib import Path

def abort(stage, http=None, retry_after=None):
    print(json.dumps({'failure': stage, 'http': http, 'retry_after': retry_after}), flush=True)
    raise SystemExit(1)

def admin_call(stage, url, body=None):
    try:
        req = urllib.request.Request('http://127.0.0.1:18790' + url, data=body,
                                     headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=10) as response:
            return json.load(response) if stage == 'admin_status' else None
    except urllib.error.HTTPError as error:
        abort(stage, http=error.code)
    except (urllib.error.URLError, OSError, ValueError):
        abort(stage)

env = None
for directory in Path('/proc').iterdir():
    if directory.name.isdigit():
        try:
            if directory.joinpath('cmdline').read_bytes().split(b'\0')[0] == b'/app/aistudio2api':
                env = dict(item.decode().split('=', 1) for item in directory.joinpath('environ').read_bytes().split(b'\0') if b'=' in item)
                break
        except (FileNotFoundError, PermissionError):
            continue
if not env or not env.get('PROXY_API_KEY'):
    abort('runtime_key')
if MODEL is None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    admin_enabled = env.get('ADMIN_AUTH_ENABLED', 'false').lower() == 'true'
    if admin_enabled:
        admin_call('admin_login', '/api/auth/login', json.dumps({'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}).encode())
    try:
        status = admin_call('admin_status', '/api/status')
    finally:
        if admin_enabled:
            admin_call('admin_logout', '/api/auth/logout', b'{}')
    if not isinstance(status, dict) or status.get('version') != EXPECTED or not status.get('ready'):
        abort('readiness')
    settings = {name: env.get(name) for name in ('WARM_WORKER_LIMIT', 'MAX_ACTIVE_WORKERS', 'WARM_STARTUP_CONCURRENCY', 'PER_ACCOUNT_CONCURRENCY', 'REQUEST_TIMEOUT', 'INIT_TIMEOUT', 'AISTUDIO_AUTH_STATES')}
    settings['proxy_key_sha256'] = hashlib.sha256(env['PROXY_API_KEY'].encode()).hexdigest()
    print(json.dumps({'version': status['version'], 'ready': status['ready'], 'settings': settings, 'probes': []}))
else:
    tools = [{'type': 'function', 'name': 'maritime_probe_%02d' % n, 'description': 'Unused. Do not invoke.', 'parameters': {'type': 'object', 'properties': {'operations': {'type': 'array'}} if n == 71 else {'value': {'type': 'string'}}}} for n in range(72)]
    body = {'model': MODEL, 'input': 'Reply with exactly MARITIME_SCHEMA_OK. Do not call any tool or function.', 'tools': tools, 'tool_choice': 'auto', 'max_output_tokens': 2048, 'stream': False}
    request = urllib.request.Request(PUBLIC + '/v1/responses', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-API-Key': env['PROXY_API_KEY']})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
        text = ''.join(part.get('text', '') for item in result.get('output', []) for part in item.get('content', []) if part.get('type') == 'output_text').strip()
        if result.get('status') != 'completed' or text != 'MARITIME_SCHEMA_OK':
            abort('marker')
    except urllib.error.HTTPError as error:
        hint = (error.headers.get('Retry-After') or '').strip()
        abort('http', error.code, int(hint) if hint.isascii() and hint.isdecimal() and len(hint) <= 8 else None)
    except (urllib.error.URLError, OSError):
        abort('transport')
    except (ValueError, TypeError, AttributeError):
        abort('invalid_response')
    print(json.dumps({'model': MODEL, 'status': 'completed', 'marker': True}))
'''

CAPACITY = r'''import json, os, sys
from pathlib import Path

browser, version = sys.argv[1:]
directory = Path(browser).parent
for cache in (directory.with_name('camoufox'), directory):
    executable = cache / 'camoufox-bin'
    ini = cache / 'application.ini'
    if (executable.is_file() and os.access(executable, os.X_OK) and ini.is_file()
            and f'Version={version}' in ini.read_text().splitlines()):
        print(json.dumps({'cached': True}))
        break
else:
    volume = os.statvfs('/data')
    print(json.dumps({'available_kib': volume.f_bavail * volume.f_frsize // 1024}))
'''


def request(method, path, body=None):
    token = os.environ.get('MARITIME_TOKEN', '').strip()
    if not token:
        raise RuntimeError('MARITIME_TOKEN secret is required')
    req = urllib.request.Request(
        API + path, data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Maritime {method} {path}: HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise RuntimeError(f'Maritime {method} {path}: network/JSON failure; inspect history before retrying POST') from None


def check_browser_capacity(browser, size_kib):
    path = re.fullmatch(r'/data/aistudio2api/runtime/camoufox-'
                        r'([0-9]+\.[0-9]+\.[0-9]+(?:-[a-z]+\.[0-9]+)?)-[0-9a-f]{64}/camoufox-bin', browser)
    if not path or not re.fullmatch(r'[1-9][0-9]{0,11}', size_kib):
        raise ValueError('Invalid Camoufox smoke-test capacity outputs')
    result = request('POST', f'/api/agents/{AGENT}/exec',
                     {'command': ['python3', '-c', CAPACITY, browser, path[1]]})
    try:
        if type(result['exitCode']) is not int or result['exitCode'] != 0:
            raise ValueError
        payload = json.loads(result['stdout'])
        if isinstance(payload, dict) and payload.get('cached') is True:
            print('Matching Camoufox cache already present on Maritime /data', flush=True)
            return
        available = payload['available_kib']
        if type(available) is not int or available < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('Unable to verify Camoufox capacity on Maritime /data') from None
    required = int(size_kib) + CAPACITY_HEADROOM_KIB
    if available < required:
        raise RuntimeError(f'Insufficient Maritime /data space for Camoufox: {available} KiB available, '
                           f'{required} KiB required (including 64 MiB headroom); main not modified')
    print(f'Maritime /data capacity verified: {available} KiB available, {required} KiB required', flush=True)


class ProbeFailure(RuntimeError):
    def __init__(self, model, payload):
        stage = payload.get('failure')
        self.stage = stage if isinstance(stage, str) and stage in PROBE_ERRORS else 'exec'
        code = payload.get('http')
        self.http = code if type(code) is int and 400 <= code <= 599 else None
        hint = payload.get('retry_after')
        self.retry_after = hint if type(hint) is int and 0 <= hint <= 99999999 else None
        details = f'HTTP {self.http}' if self.http else ''
        if self.retry_after is not None:
            details += f' retry_after={self.retry_after}s'
        super().__init__(f'{model or "runtime"}: {self.stage}' + (f' ({details.strip()})' if details else ''))


def remote_probe(version, model=None):
    code = f'EXPECTED={version!r}\nMODEL={model!r}\nPUBLIC={API + "/a/" + AGENT!r}\n' + PROBE
    result = request('POST', f'/api/agents/{AGENT}/exec', {'command': ['python3', '-c', code]})
    try:
        payload = json.loads(result.get('stdout', ''))
    except (ValueError, TypeError):
        payload = {}
    if result.get('exitCode', 0) != 0:
        # Remote stderr can contain account details; never copy it into CI logs.
        raise ProbeFailure(model, payload if isinstance(payload, dict) else {})
    if (model is not None and payload != {'model': model, 'status': 'completed', 'marker': True}) or (
            model is None and (not isinstance(payload, dict) or payload.get('version') != version
                              or payload.get('ready') is not True or not isinstance(payload.get('settings'), dict)
                              or payload.get('probes') != [])):
        raise ProbeFailure(model, {'failure': 'invalid_response'})
    return payload


def probe(version, inference=True):
    status = remote_probe(version)
    if not inference:
        return status
    failures = []
    for model in MODELS:
        for attempt, delay in enumerate((5, 15, 0), start=1):
            try:
                status['probes'].append(remote_probe(version, model))
                print(f'{model}: completed with marker', flush=True)
                break
            except ProbeFailure as error:
                print(f'Probe attempt {attempt}: {error}', flush=True)
                if attempt == 1 and error.stage == 'invalid_response':
                    time.sleep(delay)
                    continue
                if not delay or error.http not in (429, 503) or (error.retry_after or 0) > 30:
                    failures.append(str(error))
                    break
                time.sleep(max(delay, error.retry_after or 0))
    if failures:
        raise RuntimeError('Maritime schema probes failed: ' + '; '.join(failures))
    return status


def history():
    result = request('GET', f'/api/deploy/agent/{AGENT}')
    return result if isinstance(result, list) else result['deployments']


def wait_deployment(deployment_id=None):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        deployments = history()
        if deployment_id is None:
            if all(item['status'] in TERMINAL for item in deployments):
                return
        else:
            deployment = next((item for item in deployments if item['id'] == deployment_id), None)
            if deployment and deployment['status'] == 'success':
                return
            if deployment and deployment['status'] in TERMINAL:
                raise RuntimeError(f'Maritime deployment {deployment_id} failed')
        time.sleep(15)
    raise RuntimeError('Maritime deployment timed out; inspect history before retry')


def deploy(version, previous_version, rollback=False, *, skip_baseline_inference=False):
    wait_deployment()
    if rollback:
        before = json.loads(BASELINE.read_text())
    else:
        if skip_baseline_inference:
            print('Manual release: old-version inference skipped; version, readiness and settings still checked', flush=True)
        before = probe(previous_version, inference=not skip_baseline_inference)
        BASELINE.write_text(json.dumps(before))
    # Mark before POST: a lost response may still have started a deployment.
    STARTED.touch()
    result = request('POST', '/api/deploy', {'agentId': AGENT, 'source': 'github', 'repoUrl': REPO, 'branch': 'main'})
    deployment_id = result['id']
    print(json.dumps({'deployment_id': deployment_id, 'expected_version': version}), flush=True)
    wait_deployment(deployment_id)
    # A browser-version change may need to fill a new persistent cache before readiness.
    deadline = time.monotonic() + 600
    while True:
        try:
            probe(version, inference=False)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(10)
    after = probe(version)
    if before['settings'] != after['settings']:
        raise RuntimeError('Runtime configuration changed; refusing acceptance')
    print(json.dumps({'deployment_id': deployment_id, 'version': after['version'], 'ready': after['ready'], 'probes': after['probes'], 'configuration_preserved': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--previous-version')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--skip-baseline-inference', action='store_true')
    parser.add_argument('--check-browser-capacity', nargs=2, metavar=('PATH', 'KIB'))
    args = parser.parse_args()
    if args.check_browser_capacity:
        if args.version is not None or args.previous_version is not None or args.rollback or args.skip_baseline_inference:
            parser.error('capacity check cannot be combined with deployment arguments')
        check_browser_capacity(*args.check_browser_capacity)
        return
    if not all(value and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', value) for value in (args.version, args.previous_version)):
        parser.error('invalid version')
    deploy(args.version, args.previous_version, args.rollback, skip_baseline_inference=args.skip_baseline_inference)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, ValueError) as error:
        raise SystemExit(str(error)) from None
