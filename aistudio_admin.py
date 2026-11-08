import http.cookiejar
import json
import os
import urllib.parse
import urllib.request
from contextlib import contextmanager


@contextmanager
def admin_urlopen(request, timeout):
    configured = os.environ.get("AISTUDIO_ADMIN_ORIGIN", "").rstrip("/")
    parsed = urllib.parse.urlsplit(request.full_url)
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    if not configured.startswith("https://") or origin != configured:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield response
        return

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    body = json.dumps({
        "username": os.environ["AISTUDIO_ADMIN_USERNAME"],
        "password": os.environ["AISTUDIO_ADMIN_PASSWORD"],
    }).encode()
    headers = {"Content-Type": "application/json", "Origin": configured}
    login = urllib.request.Request(configured + "/api/auth/login", data=body, headers=headers)
    with opener.open(login, timeout=timeout):
        pass
    try:
        with opener.open(request, timeout=timeout) as response:
            yield response
    finally:
        logout = urllib.request.Request(configured + "/api/auth/logout", data=b"{}", headers=headers)
        try:
            with opener.open(logout, timeout=timeout):
                pass
        except (urllib.error.URLError, TimeoutError):
            pass
