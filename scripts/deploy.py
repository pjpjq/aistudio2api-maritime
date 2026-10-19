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

PROBE = r'''import hashlib, json, urllib.error, urllib.request
from pathlib import Path
status = json.load(urllib.request.urlopen('http://127.0.0.1:18790/api/status', timeout=10))
if status.get('version') != EXPECTED or not status.get('ready'):
    raise RuntimeError('runtime version/readiness mismatch')
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
    raise RuntimeError('runtime API key unavailable')
settings = {name: env.get(name) for name in ('WARM_WORKER_LIMIT', 'MAX_ACTIVE_WORKERS', 'WARM_STARTUP_CONCURRENCY', 'PER_ACCOUNT_CONCURRENCY', 'REQUEST_TIMEOUT', 'INIT_TIMEOUT', 'AISTUDIO_AUTH_STATES')}
settings['proxy_key_sha256'] = hashlib.sha256(env['PROXY_API_KEY'].encode()).hexdigest()
probes = []
if INFERENCE:
    tools = [{'type': 'function', 'name': 'maritime_probe_%02d' % n, 'description': 'Unused. Do not invoke.', 'parameters': {'type': 'object', 'properties': {'operations': {'type': 'array'}} if n == 71 else {'value': {'type': 'string'}}}} for n in range(72)]
    for model in ('gemini-3.8-flash', 'gemini-4-argon'):
        body = {'model': model, 'input': 'Reply with exactly MARITIME_SCHEMA_OK. Do not call any tool or function.', 'tools': tools, 'tool_choice': 'auto', 'max_output_tokens': 2048, 'stream': False}
        request = urllib.request.Request(PUBLIC + '/v1/responses', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-API-Key': env['PROXY_API_KEY']})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(model + ' probe HTTP ' + str(error.code)) from None
        text = ''.join(part.get('text', '') for item in result.get('output', []) for part in item.get('content', []) if part.get('type') == 'output_text').strip()
        if result.get('status') != 'completed' or text != 'MARITIME_SCHEMA_OK':
            raise RuntimeError(model + ' probe did not complete with marker')
        probes.append({'model': model, 'status': 'completed', 'marker': True})
print(json.dumps({'version': status['version'], 'ready': status['ready'], 'settings': settings, 'probes': probes}))
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


def probe(version, inference=True):
    code = f'EXPECTED={version!r}\nINFERENCE={inference!r}\nPUBLIC={API + "/a/" + AGENT!r}\n' + PROBE
    result = request('POST', f'/api/agents/{AGENT}/exec', {'command': ['python3', '-c', code]})
    if result.get('exitCode', 0) != 0:
        # Remote stderr can contain account details; never copy it into CI logs.
        raise RuntimeError('Maritime runtime/schema probe failed')
    return json.loads(result['stdout'])


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


def deploy(version, previous_version, rollback=False):
    wait_deployment()
    if rollback:
        before = json.loads(BASELINE.read_text())
    else:
        before = probe(previous_version)
        BASELINE.write_text(json.dumps(before))
    # Mark before POST: a lost response may still have started a deployment.
    STARTED.touch()
    result = request('POST', '/api/deploy', {'agentId': AGENT, 'source': 'github', 'repoUrl': REPO, 'branch': 'main'})
    deployment_id = result['id']
    print(json.dumps({'deployment_id': deployment_id, 'expected_version': version}), flush=True)
    wait_deployment(deployment_id)
    deadline = time.monotonic() + 240
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
    parser.add_argument('--version', required=True)
    parser.add_argument('--previous-version', required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if not all(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', value) for value in (args.version, args.previous_version)):
        parser.error('invalid version')
    deploy(args.version, args.previous_version, args.rollback)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, ValueError) as error:
        raise SystemExit(str(error)) from None
