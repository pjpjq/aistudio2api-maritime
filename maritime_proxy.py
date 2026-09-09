import http.client
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", 18790)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
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

    def proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length"}}
        authorization = headers.get("Authorization", "")
        if authorization.lower().startswith("bearer ") and "X-API-Key" not in headers:
            headers["X-API-Key"] = authorization[7:].strip()
        try:
            conn = http.client.HTTPConnection(*UPSTREAM, timeout=300)
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding"}:
                    self.send_header(key, value)
            self.end_headers()
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except Exception as exc:
            self.send_error(502, str(exc))

    def log_message(self, *_args):
        return


port = int(os.environ.get("PORT", "18789"))
server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
server.serve_forever()
