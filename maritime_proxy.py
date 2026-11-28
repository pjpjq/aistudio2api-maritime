import http.client
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", 18790)


class ProxyServer(ThreadingHTTPServer):
    """Threaded proxy server tuned for concurrent WebUI asset bursts."""

    request_queue_size = 128
    daemon_threads = True


def _is_event_stream_request(req_path, headers):
    """Return True when the request targets an SSE endpoint or stream."""

    if req_path.split("?", 1)[0] == "/api/events":
        return True
    return "text/event-stream" in headers.get("Accept", "").lower()


def _merge_no_transform(cache_control):
    """Append no-transform to Cache-Control unless already present."""

    directives = [part.strip().lower() for part in cache_control.split(",") if part.strip()]
    if "no-transform" in directives:
        return cache_control
    return f"{cache_control}, no-transform" if cache_control.strip() else "no-transform"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.proxy()

    def do_HEAD(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "15")
            self.end_headers()
            return
        self.proxy()

    def do_POST(self):
        if self.path == "/chat":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"response":"Use the OpenAI-compatible /v1 API for inference."}')
            return
        self.proxy()

    def do_PUT(self):
        self.proxy()

    def do_DELETE(self):
        self.proxy()

    def do_PATCH(self):
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()

    def proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        is_sse_req = _is_event_stream_request(self.path, self.headers)
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() != "content-length"
            and not (is_sse_req and k.lower() == "accept-encoding")
        }
        if is_sse_req:
            headers["Accept-Encoding"] = "identity"
        has_x_api_key = any(k.lower() == "x-api-key" for k in headers)
        authorization = next(
            (v for k, v in headers.items() if k.lower() == "authorization"),
            "",
        )
        if authorization.lower().startswith("bearer ") and not has_x_api_key:
            headers["X-API-Key"] = authorization[7:].strip()

        conn = None
        headers_sent = False
        try:
            conn = http.client.HTTPConnection(*UPSTREAM, timeout=300)
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            resp_headers = response.getheaders()
            is_sse_resp = any(
                k.lower() == "content-type"
                and v.split(";", 1)[0].strip().lower() == "text/event-stream"
                for k, v in resp_headers
            )
            has_cache_control = False
            for key, value in resp_headers:
                lower_key = key.lower()
                if lower_key in {"connection", "transfer-encoding"}:
                    continue
                if is_sse_resp and lower_key == "cache-control":
                    has_cache_control = True
                    value = _merge_no_transform(value)
                self.send_header(key, value)
            if is_sse_resp and not has_cache_control:
                self.send_header("Cache-Control", "no-cache, no-transform")
            self.end_headers()
            headers_sent = True
            if self.command == "HEAD":
                return
            read_chunk = (
                response.read1
                if isinstance(response, http.client.HTTPResponse)
                else response.read
            )
            while True:
                chunk = read_chunk(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            if not headers_sent:
                self.send_error(502, str(exc))
        finally:
            if conn is not None:
                conn.close()

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "18789"))
    server = ProxyServer(("0.0.0.0", port), Handler)
    server.serve_forever()
