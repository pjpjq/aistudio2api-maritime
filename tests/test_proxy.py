import errno
import http.client
import io
import socket
import threading
import time
import unittest
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from maritime_proxy import Handler, ProxyServer


class ProxyStreamingAndMethodsTests(unittest.TestCase):
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

    def test_proxy_server_tuning_prevents_backlog_overflow(self):
        self.assertGreaterEqual(ProxyServer.request_queue_size, 128)
        self.assertTrue(ProxyServer.daemon_threads)

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_delete_head_patch_options_are_forwarded(self, connection):
        for method, path, status, resp_body in [
            ("DELETE", "/api/accounts/acc-1", 204, b""),
            ("HEAD", "/api/status", 200, b""),
            ("PATCH", "/api/accounts/acc-1", 200, b'{"ok":true}'),
            ("OPTIONS", "/v1/models", 204, b""),
        ]:
            with self.subTest(method=method):
                connection.reset_mock()
                response = connection.return_value.getresponse.return_value
                response.status = status
                response.getheaders.return_value = []
                response.read.side_effect = [resp_body, b""] if resp_body else [b""]
                req_headers = {
                    "Host": "console.example.test",
                    "Origin": "https://console.example.test",
                    "Cookie": "aistudio_admin=dummy-session",
                }
                handler = self.handler(method, path, b"", req_headers)
                getattr(handler, "do_" + method)()
                connection.return_value.request.assert_called_once_with(
                    method, path, body=None, headers=req_headers
                )
                handler.send_response.assert_called_once_with(status)
                connection.return_value.close.assert_called_once()

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_health_head_returns_200_without_body(self, connection):
        handler = self.handler("HEAD", "/health")
        handler.do_HEAD()
        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "application/json")
        self.assertEqual(handler.wfile.getvalue(), b"")
        connection.assert_not_called()

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_sse_forces_identity_and_no_transform_headers(self, connection):
        for upstream_headers, expected_cache_control in [
            ([("Content-Type", "text/event-stream"), ("Cache-Control", "no-cache")], "no-cache, no-transform"),
            ([("Content-Type", "text/event-stream; charset=utf-8")], "no-cache, no-transform"),
            ([("Content-Type", "text/event-stream"), ("Cache-Control", "no-cache, no-transform")], "no-cache, no-transform"),
        ]:
            with self.subTest(expected=expected_cache_control, upstream_headers=upstream_headers):
                connection.reset_mock()
                response = connection.return_value.getresponse.return_value
                response.status = 200
                response.getheaders.return_value = upstream_headers
                response.read.side_effect = [b"data: {}\n\n", b""]
                handler = self.handler(
                    "GET",
                    "/api/events",
                    headers={"Accept": "text/event-stream", "Accept-Encoding": "gzip, deflate, br"},
                )

                handler.do_GET()

                forwarded = connection.return_value.request.call_args.kwargs["headers"]
                self.assertEqual(forwarded["Accept-Encoding"], "identity")
                handler.send_header.assert_any_call("Cache-Control", expected_cache_control)

    @patch("maritime_proxy.http.client.HTTPConnection")
    def test_broken_pipe_after_headers_does_not_call_send_error(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = [("Content-Type", "text/event-stream")]
        response.read.return_value = b"data: {}\n\n"
        handler = self.handler("GET", "/api/events")
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()

        handler.do_GET()

        handler.send_error.assert_not_called()
        connection.return_value.close.assert_called_once()

    def test_socketpair_http_response_streams_small_chunk_immediately(self):
        server_sock, client_sock = socket.socketpair()
        payload = b'data: {"type":"accounts","data":{"accounts":[]}}\n\n'
        raw_http = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            + f"{len(payload):x}\r\n".encode("ascii")
            + payload
            + b"\r\n"
        )
        server_sock.sendall(raw_http)

        response = http.client.HTTPResponse(client_sock, method="GET")
        response.begin()

        handler = self.handler("GET", "/api/events")
        received = bytearray()

        class FlushedWriter:
            def write(self, data):
                received.extend(data)

            def flush(self):
                if bytes(received) == payload:
                    server_sock.close()

        handler.wfile = FlushedWriter()
        fake_conn = Mock()
        fake_conn.getresponse.return_value = response

        t0 = time.monotonic()
        with patch("maritime_proxy.http.client.HTTPConnection", return_value=fake_conn):
            try:
                handler.do_GET()
            except http.client.IncompleteRead:
                pass
        elapsed = time.monotonic() - t0
        client_sock.close()

        self.assertLess(elapsed, 1.0)
        self.assertEqual(bytes(received), payload)
        fake_conn.close.assert_called_once()

    def test_loopback_proxy_streams_small_sse_without_waiting_for_64k(self):
        stop_event = threading.Event()
        seen_accept_encoding = []
        payload = b'data: {"type":"accounts","data":{"accounts":[{"id":"a1"}]}}\n\n'

        class MockUpstreamHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                seen_accept_encoding.append(self.headers.get("Accept-Encoding"))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                frame = f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n"
                self.wfile.write(frame)
                self.wfile.flush()
                stop_event.wait(timeout=5)

            def log_message(self, *_args):
                return

        try:
            upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockUpstreamHandler)
        except OSError as exc:
            if exc.errno == errno.EADDRNOTAVAIL:
                self.skipTest("loopback interface unavailable in isolated network namespace")
            raise
        proxy = ProxyServer(("127.0.0.1", 0), Handler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        upstream_thread.start()
        proxy_thread.start()

        try:
            with patch("maritime_proxy.UPSTREAM", upstream.server_address):
                sock = socket.create_connection(proxy.server_address, timeout=2)
                sock.settimeout(1.0)
                sock.sendall(
                    b"GET /api/events HTTP/1.1\r\n"
                    b"Host: 127.0.0.1\r\n"
                    b"Accept: text/event-stream\r\n"
                    b"Accept-Encoding: gzip, deflate, br\r\n\r\n"
                )
                t0 = time.monotonic()
                buf = b""
                while payload not in buf and time.monotonic() - t0 < 1.5:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                elapsed = time.monotonic() - t0
                sock.close()
        finally:
            stop_event.set()
            proxy.shutdown()
            proxy.server_close()
            upstream.shutdown()
            upstream.server_close()

        self.assertLess(elapsed, 1.0)
        self.assertIn(payload, buf)
        self.assertIn(b"Cache-Control: no-cache, no-transform\r\n", buf)
        self.assertEqual(seen_accept_encoding, ["identity"])


if __name__ == "__main__":
    unittest.main()
