"""Local fake Amazon + Telegram + Green API server used by the end-to-end tests."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class MockWorld:
    def __init__(self):
        self.pages = {}      # asin -> (status, html)
        self.requests = []   # recorded notification POSTs: (path, json)
        self.fail_notify = False
        self.httpd = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def start(self):
        world = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                b = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path.startswith("/dp/"):
                    asin = self.path.split("/dp/")[1].split("?")[0]
                    code, html = world.pages.get(asin, (404, "<html><title>Page Not Found</title></html>"))
                    return self._send(code, html)
                self._send(404, "nope")

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
                world.requests.append((self.path, data))
                if world.fail_notify:
                    return self._send(500, "{}", "application/json")
                if "/sendMessage/" in self.path:      # Green API
                    return self._send(200, json.dumps({"idMessage": "ABC123"}), "application/json")
                if self.path.endswith("/sendMessage"):  # Telegram
                    return self._send(200, json.dumps({"ok": True, "result": {}}), "application/json")
                self._send(404, "{}", "application/json")

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
