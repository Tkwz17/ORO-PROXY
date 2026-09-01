#!/usr/bin/env python3
"""HTTP setup portal with a deliberately tiny, allow-listed API bridge.

The AP must be usable before a browser has trusted OroProxy's per-device HTTPS
certificate.  Only Wi-Fi onboarding endpoints are bridged over HTTP; every
admin, account, quota, and proxy API remains available only on HTTPS :8443.
"""
import http.client
import os
import ssl
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_ROOT = Path(os.getenv("OROPROXY_WEB_ROOT", "/opt/oroproxy/services/portal-web"))
API_HOST = os.getenv("OROPROXY_LOCAL_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("OROPROXY_LOCAL_API_PORT", "8443"))
ONBOARDING_PATHS = {"/api/network/state", "/api/network/connect"}


class PortalHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        # Serve only from WEB_ROOT, rather than the service process CWD.
        relative = Path(urlparse(path).path).as_posix().lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return str(WEB_ROOT / "__not_found__")
        return str(candidate)

    def do_GET(self) -> None:
        if urlparse(self.path).path in ONBOARDING_PATHS:
            self._bridge()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/network/connect":
            self._bridge()
            return
        self.send_error(404)

    def _bridge(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            conn = http.client.HTTPSConnection(API_HOST, API_PORT, timeout=35, context=ssl._create_unverified_context())
            conn.request(self.command, urlparse(self.path).path, body=body, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            payload = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            conn.close()
        except OSError:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"setup service temporarily unavailable"}')


def main() -> None:
    os.chdir(WEB_ROOT)
    ThreadingHTTPServer((os.getenv("OROPROXY_WEB_BIND", "0.0.0.0"), int(os.getenv("OROPROXY_WEB_PORT", "80"))), PortalHandler).serve_forever()


if __name__ == "__main__":
    main()
