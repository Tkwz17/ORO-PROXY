import importlib.util
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("portal_server", ROOT / "server.py")
portal_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal_server)


class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"mode":"ap"}')

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def test_only_onboarding_routes_are_bridged(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    # The test certificate is supplied by openssl, as is the production certificate.
    assert os.system(f"openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost -keyout {key} -out {cert} >/dev/null 2>&1") == 0
    api = ThreadingHTTPServer(("127.0.0.1", 0), APIHandler)
    api.socket = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).wrap_socket(api.socket, server_side=True)
    api.socket.context.load_cert_chain(cert, key)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    monkeypatch.setattr(portal_server, "API_PORT", api.server_port)
    monkeypatch.setattr(portal_server, "WEB_ROOT", ROOT)

    web = ThreadingHTTPServer(("127.0.0.1", 0), portal_server.PortalHandler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        with urlopen(f"http://127.0.0.1:{web.server_port}/api/network/state") as response:
            assert json.load(response) == {"mode": "ap"}
        request = Request(f"http://127.0.0.1:{web.server_port}/api/network/connect", data=b'{"ssid":"Home"}', method="POST")
        with urlopen(request) as response:
            assert json.load(response) == {"ssid": "Home"}
        try:
            urlopen(f"http://127.0.0.1:{web.server_port}/api/users")
            assert False, "non-onboarding endpoint was exposed over HTTP"
        except Exception as exc:
            assert getattr(exc, "code", None) == 404
    finally:
        web.shutdown()
        api.shutdown()
