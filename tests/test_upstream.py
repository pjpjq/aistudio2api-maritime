import contextlib
import copy
import io
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/upstream.py'
DOCKERFILE = '''FROM debian:bookworm-slim
ARG AISTUDIO_VERSION=v0.2.13
ARG AISTUDIO_SHA256=31c5b16e5a2e84e932dcbc13364f04e58b7bd0c6a699cc1465c5d7443d4e6e51
RUN curl https://github.com/daijro/camoufox/releases/download/v152.0.4-beta.29/camoufox-152.0.4-beta.29-lin.x86_64.zip
'''


class Response(io.BytesIO):
    status = 200


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.original_cwd)
        self.docker = self.root / 'Dockerfile'
        self.docker.write_text(DOCKERFILE)
        self.output = self.root / 'output'
        self.calls = []
        self.browser = '152.0.4-beta.29'
        self.release = {
            'tag_name': 'v0.2.14', 'draft': False, 'prerelease': False,
            'assets': [{
                'name': 'aistudio2api-v0.2.14-linux-amd64.tar.gz',
                'browser_download_url': 'https://github.com/Mag1cFall/AIStudio2API/releases/download/v0.2.14/aistudio2api-v0.2.14-linux-amd64.tar.gz',
                'digest': 'sha256:' + 'b' * 64,
            }],
        }

    def fetch(self, request, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        headers = {} if isinstance(request, str) else {key.lower(): value for key, value in request.header_items()}
        self.calls.append((url, headers))
        if url == 'https://api.github.com/repos/Mag1cFall/AIStudio2API/releases/latest':
            return Response(json.dumps(self.release).encode())
        if url.startswith('https://raw.githubusercontent.com/Mag1cFall/AIStudio2API/'):
            return Response(('const camoufoxRelease = "' + self.browser + '"').encode())
        raise AssertionError('Unexpected URL: ' + url)

    def command(self, *args):
        self.output.write_text('')
        opener = Mock()
        opener.open.side_effect = self.fetch
        with patch.dict(os.environ, {'GITHUB_OUTPUT': str(self.output), 'GITHUB_TOKEN': 'unit-test-token'}), \
             patch('sys.argv', [str(SCRIPT), *args]), \
             patch('urllib.request.urlopen', side_effect=self.fetch), \
             patch('urllib.request.build_opener', return_value=opener), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as error:
                if error.code not in (None, 0):
                    raise RuntimeError('upstream command rejected input') from error
        return dict(line.split('=', 1) for line in self.output.read_text().splitlines())

    def test_new_release_updates_only_two_pins(self):
        result = self.command('check')
        expected = DOCKERFILE.replace('ARG AISTUDIO_VERSION=v0.2.13', 'ARG AISTUDIO_VERSION=v0.2.14').replace(
            'ARG AISTUDIO_SHA256=31c5b16e5a2e84e932dcbc13364f04e58b7bd0c6a699cc1465c5d7443d4e6e51',
            'ARG AISTUDIO_SHA256=' + 'b' * 64,
        )
        self.assertEqual(self.docker.read_text(), expected)
        self.assertEqual(result['changed'], 'true')
        self.assertEqual(result['version'], 'v0.2.14')
        self.assertEqual(result['previous_version'], 'v0.2.13')
        for url, headers in self.calls:
            if 'raw.githubusercontent.com' in url:
                self.assertNotIn('authorization', headers)

    def test_same_release_is_noop(self):
        self.release['tag_name'] = 'v0.2.13'
        asset = self.release['assets'][0]
        asset['name'] = asset['name'].replace('v0.2.14', 'v0.2.13')
        asset['browser_download_url'] = asset['browser_download_url'].replace('v0.2.14', 'v0.2.13')
        asset['digest'] = 'sha256:31c5b16e5a2e84e932dcbc13364f04e58b7bd0c6a699cc1465c5d7443d4e6e51'
        self.assertEqual(self.command('check')['changed'], 'false')
        self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_invalid_release_fails_without_editing(self):
        original = copy.deepcopy(self.release)
        cases = [
            ('prerelease', True), ('draft', True), ('tag_name', 'v1.0.0;touch /tmp/x'),
            ('assets', []),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                self.release = dict(copy.deepcopy(original), **{field: value})
                with self.assertRaises((RuntimeError, ValueError)):
                    self.command('check')
                self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_invalid_asset_fails_without_editing(self):
        original = copy.deepcopy(self.release)
        for field, value in (
            ('digest', None), ('digest', 'sha256:bad'), ('digest', 'a' * 64),
            ('browser_download_url', 'https://attacker.invalid/payload'),
        ):
            with self.subTest(field=field, value=value):
                self.release = copy.deepcopy(original)
                self.release['assets'][0][field] = value
                with self.assertRaises((RuntimeError, ValueError)):
                    self.command('check')
                self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_browser_change_fails_closed(self):
        self.browser = '999.0'
        with self.assertRaises((RuntimeError, ValueError)):
            self.command('check')
        self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_same_version_changed_digest_is_rejected(self):
        self.release['tag_name'] = 'v0.2.13'
        asset = self.release['assets'][0]
        asset['name'] = asset['name'].replace('v0.2.14', 'v0.2.13')
        asset['browser_download_url'] = asset['browser_download_url'].replace('v0.2.14', 'v0.2.13')
        with self.assertRaises((RuntimeError, ValueError)):
            self.command('check')
        self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_downgrade_never_edits_pins(self):
        self.release['tag_name'] = 'v0.2.12'
        asset = self.release['assets'][0]
        asset['name'] = asset['name'].replace('v0.2.14', 'v0.2.12')
        asset['browser_download_url'] = asset['browser_download_url'].replace('v0.2.14', 'v0.2.12')
        with self.assertRaises((RuntimeError, ValueError)):
            self.command('check')
        self.assertEqual(self.docker.read_text(), DOCKERFILE)

    def test_gate_record_and_force(self):
        self.assertEqual(self.command('gate')['due'], 'true')
        self.command('record')
        self.assertEqual(self.command('gate')['due'], 'false')
        self.assertEqual(self.command('gate', '--force')['due'], 'true')
        self.assertEqual(self.calls, [])

    def test_corrupt_state_fails_closed(self):
        Path('.upstream-check-state').write_text('bad timestamp')
        with self.assertRaises((RuntimeError, ValueError)):
            self.command('gate')


if __name__ == '__main__':
    unittest.main()
