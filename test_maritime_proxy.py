import io
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from maritime_proxy import Handler, UPSTREAM


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


if __name__ == "__main__":
    unittest.main()
