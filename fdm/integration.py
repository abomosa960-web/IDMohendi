"""خادم محلي يستقبل الروابط من إضافة المتصفح.

يعمل على 127.0.0.1 فقط، ولا يقبل أي طلب بدون التوكن الخاص بالجهاز،
حتى لا تستطيع المواقع الأخرى تشغيل تحميلات من غير علمك.
"""
from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .manager import DownloadManager

MAX_BODY = 64 * 1024


def _make_handler(manager: DownloadManager, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FreeDM"

        def log_message(self, *args):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-FreeDM-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def _reply(self, code: int, payload: dict | None = None):
            body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self):
            if urlparse(self.path).path != "/add":
                return self._reply(404, {"ok": False, "error": "not found"})

            given = self.headers.get("X-FreeDM-Token", "")
            if not hmac.compare_digest(given, token):
                return self._reply(403, {"ok": False, "error": "bad token"})

            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._reply(400, {"ok": False, "error": "bad body"})
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._reply(400, {"ok": False, "error": "bad json"})

            url = str(data.get("url", ""))
            if urlparse(url).scheme not in ("http", "https"):
                return self._reply(400, {"ok": False, "error": "bad url"})

            headers = {}
            if data.get("cookies"):
                headers["Cookie"] = str(data["cookies"])[:8000]
            if data.get("referer"):
                headers["Referer"] = str(data["referer"])[:2000]

            job = manager.add(url, headers=headers or None)
            return self._reply(200, {"ok": True, "id": job.id})

    return Handler


class IntegrationServer:
    def __init__(self, manager: DownloadManager, port: int, token: str):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(manager, token))
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="fdm-api", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
