import io
import json
import os
import unittest
import urllib.request
from email.message import Message
from unittest.mock import Mock, patch

from maritime_proxy import Handler, UPSTREAM
from aistudio_admin import admin_urlopen
from scripts import deploy


class ProxyTests(unittest.TestCase):
    def handler(self, method, path, body=b"", headers=None):
        handler = object.__new__(Handler)
        handler.command = method
        handler.path = path
        handler.headers = Message()
        for key, value in (headers or {}).items():
            handler.headers[key] = value
        handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.send_error = Mock()
        return handler

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_put_forwards_config_body_and_session(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = [("Content-Type", "application/json")]
        response.read.side_effect = [b'{"saved":true}', b""]
        body = b'{"example":"unchanged"}'
        headers = {
            "Host": "console.example.test",
            "Origin": "https://console.example.test",
            "Cookie": "aistudio_admin=dummy-session",
            "Content-Type": "application/json",
            "X-Forwarded-Proto": "https",
        }
        handler = self.handler("PUT", "/api/config", body, headers)

        handler.do_PUT()

        connection.assert_called_once_with(*UPSTREAM, timeout=300)
        connection.return_value.request.assert_called_once_with(
            "PUT", "/api/config", body=body, headers=headers
        )
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(handler.wfile.getvalue(), b'{"saved":true}')
        handler.send_error.assert_not_called()

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_login_preserves_origin_and_session_cookie(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        cookie = "aistudio_admin=dummy-session; Path=/api; HttpOnly; Secure; SameSite=Strict"
        response.getheaders.return_value = [("Set-Cookie", cookie)]
        response.read.side_effect = [b"{}", b""]
        handler = self.handler(
            "POST", "/api/auth/login", b"{}",
            {"Host": "console.example.test", "Origin": "https://console.example.test"},
        )

        handler.do_POST()

        forwarded = connection.return_value.request.call_args.kwargs["headers"]
        self.assertEqual(forwarded["Host"], "console.example.test")
        self.assertEqual(forwarded["Origin"], "https://console.example.test")
        handler.send_header.assert_any_call("Set-Cookie", cookie)

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_put_preserves_unauthorized_response(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 401
        response.getheaders.return_value = []
        response.read.side_effect = [b'{"error":"admin_login_required"}', b""]
        handler = self.handler("PUT", "/api/config", b"{}")

        handler.do_PUT()

        handler.send_response.assert_called_once_with(401)
        self.assertEqual(handler.wfile.getvalue(), b'{"error":"admin_login_required"}')

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_bearer_api_key_forwarding_is_unchanged(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = []
        response.read.side_effect = [b"{}", b""]
        handler = self.handler("GET", "/v1/models", headers={"Authorization": "Bearer dummy-key"})

        handler.do_GET()

        forwarded = connection.return_value.request.call_args.kwargs["headers"]
        self.assertEqual(forwarded["X-API-Key"], "dummy-key")
        self.assertEqual(forwarded["Authorization"], "Bearer dummy-key")

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_platform_health_and_chat_stay_public(self, connection):
        for method, path in [("GET", "/health"), ("POST", "/chat")]:
            with self.subTest(path=path):
                handler = self.handler(method, path)
                getattr(handler, "do_" + method)()
                handler.send_response.assert_called_once_with(200)
        connection.assert_not_called()


class KeepaliveLoginTests(unittest.TestCase):
    credentials = {
        "AISTUDIO_ADMIN_ORIGIN": "https://console.example.test",
        "AISTUDIO_ADMIN_USERNAME": "dummy-admin",
        "AISTUDIO_ADMIN_PASSWORD": "dummy-password",
    }

    @patch.dict(os.environ, credentials, clear=True)
    @patch("aistudio_admin.urllib.request.build_opener")
    @patch("aistudio_admin.urllib.request.urlopen")
    def test_other_origins_never_receive_credentials(self, urlopen, build_opener):
        for url in ["https://other.example.test/api/status", "http://console.example.test/api/status"]:
            request = urllib.request.Request(url)
            with admin_urlopen(request, timeout=3):
                pass
            self.assertIs(urlopen.call_args.args[0], request)
        build_opener.assert_not_called()

    @patch.dict(os.environ, credentials, clear=True)
    @patch("aistudio_admin.urllib.request.build_opener")
    def test_matching_origin_logs_in_and_logs_out(self, build_opener):
        request = urllib.request.Request("https://console.example.test/api/status")
        with admin_urlopen(request, timeout=3):
            pass
        calls = build_opener.return_value.open.call_args_list
        self.assertEqual(len(calls), 3)
        login = calls[0].args[0]
        self.assertEqual(login.full_url, "https://console.example.test/api/auth/login")
        self.assertEqual(json.loads(login.data), {"username": "dummy-admin", "password": "dummy-password"})
        self.assertIs(calls[1].args[0], request)
        self.assertEqual(calls[2].args[0].full_url, "https://console.example.test/api/auth/logout")

    @patch.dict(os.environ, credentials, clear=True)
    @patch("aistudio_admin.urllib.request.build_opener")
    def test_failed_probe_still_logs_out(self, build_opener):
        request = urllib.request.Request("https://console.example.test/api/status")
        with self.assertRaises(ValueError):
            with admin_urlopen(request, timeout=3):
                raise ValueError("dummy probe failure")
        self.assertEqual(build_opener.return_value.open.call_args.args[0].full_url, "https://console.example.test/api/auth/logout")


class DeploymentLoginTests(unittest.TestCase):
    def test_release_probe_supports_native_login_and_legacy_mode(self):
        for enabled in [False, True]:
            with self.subTest(admin_enabled=enabled):
                environment = {"PROXY_API_KEY": "dummy-api-key"}
                if enabled:
                    environment.update({"ADMIN_AUTH_ENABLED": "true", "ADMIN_USERNAME": "dummy-admin", "ADMIN_PASSWORD": "dummy-password"})
                process = Mock()
                process.name = "123"
                raw_environment = b"\0".join((key + "=" + value).encode() for key, value in environment.items())
                process.joinpath.side_effect = lambda name: Mock(read_bytes=Mock(return_value=b"/app/aistudio2api\0" if name == "cmdline" else raw_environment))
                response = io.BytesIO(json.dumps({"version": "v0.3.2", "ready": True}).encode())
                opener = Mock()
                opener.open.side_effect = [io.BytesIO(), response, io.BytesIO()] if enabled else [response]
                with patch("pathlib.Path.iterdir", return_value=[process]), patch("urllib.request.build_opener", return_value=opener), patch("builtins.print") as output:
                    exec(deploy.PROBE, {"EXPECTED": "v0.3.2", "INFERENCE": False, "PUBLIC": "https://console.example.test"})
                self.assertTrue(json.loads(output.call_args.args[0])["ready"])
                calls = opener.open.call_args_list
                self.assertEqual(len(calls), 3 if enabled else 1)
                if enabled:
                    self.assertTrue(calls[0].args[0].full_url.endswith("/api/auth/login"))
                    self.assertTrue(calls[-1].args[0].full_url.endswith("/api/auth/logout"))


if __name__ == "__main__":
    unittest.main()
