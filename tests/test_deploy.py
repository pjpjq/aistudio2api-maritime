import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from scripts import deploy


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, filename in (('BASELINE', 'baseline.json'), ('STARTED', 'started')):
            patched = patch.object(deploy, name, Path(self.temp.name) / filename)
            patched.start()
            self.addCleanup(patched.stop)
        self.before = {'version': 'v0.2.13', 'ready': True, 'settings': {'proxy_key_sha256': 'hash'}, 'probes': []}
        self.after = dict(self.before, version='v0.2.14')

    def test_remote_probe_is_valid_python(self):
        compile('EXPECTED="v0.2.13"\nMODEL=None\nPUBLIC="https://api.maritime.sh/a/test"\n' + deploy.PROBE, '<remote>', 'exec')

    @patch.object(deploy, 'request')
    def test_capacity_checks_measured_size_plus_headroom(self, request):
        browser = '/data/aistudio2api/runtime/camoufox-158.0.1-beta.41-' + 'a' * 64 + '/camoufox-bin'
        required = 200000 + deploy.CAPACITY_HEADROOM_KIB
        request.return_value = {'exitCode': 0, 'stdout': json.dumps({'available_kib': required - 1})}
        with self.assertRaisesRegex(RuntimeError, 'Insufficient Maritime /data.*main not modified'):
            deploy.check_browser_capacity(browser, '200000')
        self.assertFalse(deploy.STARTED.exists())
        request.assert_called_once_with('POST', f'/api/agents/{deploy.AGENT}/exec', {
            'command': ['python3', '-c', deploy.CAPACITY, browser, '158.0.1-beta.41'],
        })
        for result in ({'available_kib': required}, {'cached': True}):
            request.return_value = {'exitCode': 0, 'stdout': json.dumps(result)}
            with redirect_stdout(io.StringIO()):
                deploy.check_browser_capacity(browser, '200000')

    @patch.object(deploy, 'request')
    def test_capacity_rejects_invalid_inputs_and_exec_results(self, request):
        browser = '/data/aistudio2api/runtime/camoufox-158.0.1-beta.41-' + 'a' * 64 + '/camoufox-bin'
        for path, size in ((browser + '\nfoo=bar', '1'), (browser, '0'), (browser, '200 KiB')):
            with self.subTest(path=path, size=size), self.assertRaisesRegex(ValueError, 'Invalid Camoufox'):
                deploy.check_browser_capacity(path, size)
        request.assert_not_called()
        for result in ({'exitCode': 1, 'stdout': '{"cached":true}', 'stderr': 'sensitive'},
                       {'stdout': '{"cached":true}'}, {'exitCode': 0, 'stdout': '{"available_kib":true}'}):
            with self.subTest(result=result), self.assertRaisesRegex(RuntimeError, '^Unable to verify Camoufox capacity on Maritime /data$'):
                request.return_value = result
                deploy.check_browser_capacity(browser, '1')

    def test_remote_capacity_recognizes_exact_executable_cache(self):
        root = Path(self.temp.name)
        browser = root / 'camoufox-158.0.1-beta.41-hash' / 'camoufox-bin'
        for name, version, mode, cached in (('camoufox', '158.0.1-beta.41', 0o755, True),
                                            (browser.parent.name, '158.0.1-beta.41', 0o644, False),
                                            (browser.parent.name, '158.0.1-beta.40', 0o755, False),
                                            (browser.parent.name, '158.0.1-beta.41', 0o755, True)):
            with self.subTest(name=name, version=version, mode=mode), tempfile.TemporaryDirectory(dir=root) as tmp:
                cache = Path(tmp) / name
                cache.mkdir()
                executable = cache / browser.name
                executable.touch()
                executable.chmod(mode)
                (cache / 'application.ini').write_text(f'[App]\nVersion={version}\n')
                fs = SimpleNamespace(f_bavail=3, f_frsize=4096)
                with patch('sys.argv', ['-c', str(Path(tmp) / browser.parent.name / browser.name), '158.0.1-beta.41']), \
                     patch.object(deploy.os, 'statvfs', return_value=fs) as statvfs, redirect_stdout(io.StringIO()) as output:
                    exec(deploy.CAPACITY, {})
                self.assertEqual(json.loads(output.getvalue()), {'cached': True} if cached else {'available_kib': 12})
                if cached:
                    statvfs.assert_not_called()
                else:
                    statvfs.assert_called_once_with('/data')

    @patch.object(deploy, 'request')
    def test_failed_exec_does_not_log_secrets(self, request):
        request.return_value = {'exitCode': 1, 'stderr': 'secret-runtime-key', 'stdout': '{"failure":"secret"}'}
        with self.assertRaisesRegex(RuntimeError, '^runtime: exec$'):
            deploy.probe('v0.2.13')

    @patch.object(deploy.time, 'sleep')
    @patch.object(deploy, 'remote_probe')
    def test_short_quota_and_service_errors_retry_within_bound(self, check, sleep):
        flash, argon = deploy.MODELS
        flash_ok = {'model': flash, 'status': 'completed', 'marker': True}
        argon_ok = dict(flash_ok, model=argon)
        check.side_effect = [self.before, deploy.ProbeFailure(flash, {'failure': 'http', 'http': 429, 'retry_after': 8}),
                             deploy.ProbeFailure(flash, {'failure': 'http', 'http': 503}), flash_ok, argon_ok]
        self.assertEqual(deploy.probe('v0.2.13')['probes'], [flash_ok, argon_ok])
        self.assertEqual(sleep.call_args_list, [call(8), call(15)])

    @patch.object(deploy.time, 'sleep')
    @patch.object(deploy, 'remote_probe')
    def test_long_quota_and_marker_failure_still_reject_both_models(self, check, sleep):
        flash, argon = deploy.MODELS
        check.side_effect = [self.before, deploy.ProbeFailure(flash, {'failure': 'http', 'http': 429, 'retry_after': 66000}),
                             deploy.ProbeFailure(argon, {'failure': 'marker'})]
        with self.assertRaisesRegex(RuntimeError, 'gemini-3.8-flash: http.*429.*gemini-4-argon: marker'):
            deploy.probe('v0.2.13')
        sleep.assert_not_called()
        self.assertEqual(check.call_args_list, [call('v0.2.13'), call('v0.2.13', flash), call('v0.2.13', argon)])

    @patch.object(deploy, 'history')
    def test_wait_rejects_failure(self, history):
        history.return_value = [{'id': 'candidate', 'status': 'failed'}]
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            deploy.wait_deployment('candidate')

    @patch.object(deploy.time, 'sleep')
    @patch.object(deploy, 'history')
    def test_wait_matches_exact_deployment(self, history, sleep):
        history.side_effect = [
            [{'id': 'other', 'status': 'success'}, {'id': 'candidate', 'status': 'building'}],
            [{'id': 'candidate', 'status': 'success'}],
        ]
        deploy.wait_deployment('candidate')
        sleep.assert_called_once_with(15)

    @patch.object(deploy, 'wait_deployment')
    @patch.object(deploy, 'request', return_value={'id': 'candidate'})
    @patch.object(deploy, 'probe')
    def test_deploy_preserves_baseline_and_configuration(self, probe, request, wait):
        probe.side_effect = [self.before, self.after, self.after]
        deploy.deploy('v0.2.14', 'v0.2.13')
        self.assertEqual(json.loads(deploy.BASELINE.read_text()), self.before)
        self.assertTrue(deploy.STARTED.exists())
        self.assertEqual(request.call_args.args[2]['branch'], 'main')
        self.assertEqual(probe.call_args_list[0], call('v0.2.13', inference=True))

    @patch.object(deploy, 'wait_deployment')
    @patch.object(deploy, 'request', return_value={'id': 'candidate'})
    @patch.object(deploy, 'probe')
    def test_manual_release_skips_only_old_inference(self, probe, request, wait):
        probe.side_effect = [self.before, self.after, self.after]
        deploy.deploy('v0.2.14', 'v0.2.13', skip_baseline_inference=True)
        self.assertEqual(probe.call_args_list, [call('v0.2.13', inference=False),
                                               call('v0.2.14', inference=False), call('v0.2.14')])
        self.assertEqual(json.loads(deploy.BASELINE.read_text()), self.before)

    @patch.object(deploy, 'wait_deployment')
    @patch.object(deploy, 'request', side_effect=RuntimeError('network failure'))
    @patch.object(deploy, 'probe')
    def test_ambiguous_post_is_marked_and_not_retried(self, probe, request, wait):
        probe.return_value = self.before
        with self.assertRaisesRegex(RuntimeError, 'network failure'):
            deploy.deploy('v0.2.14', 'v0.2.13')
        self.assertTrue(deploy.STARTED.exists())
        request.assert_called_once()

    @patch.object(deploy, 'wait_deployment')
    @patch.object(deploy, 'request', return_value={'id': 'rollback'})
    @patch.object(deploy, 'probe')
    def test_rollback_does_not_require_healthy_candidate(self, probe, request, wait):
        deploy.BASELINE.write_text(json.dumps(self.before))
        probe.return_value = self.before
        deploy.deploy('v0.2.13', 'v0.2.14', rollback=True)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(probe.call_args.args, ('v0.2.13',))

    @patch.object(deploy, 'wait_deployment')
    @patch.object(deploy, 'request', return_value={'id': 'candidate'})
    @patch.object(deploy, 'probe')
    def test_configuration_change_fails_acceptance(self, probe, request, wait):
        probe.side_effect = [self.before, self.after, dict(self.after, settings={'proxy_key_sha256': 'changed'})]
        with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
            deploy.deploy('v0.2.14', 'v0.2.13')


if __name__ == '__main__':
    unittest.main()
