import os
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fdm import core  # noqa: E402

DATA = os.urandom(3 * 1024 * 1024 + 12345)  # ~3 MB، يُقسَّم لعدة أجزاء


class Handler(BaseHTTPRequestHandler):
    support_ranges = True
    slow = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = DATA
        rng = self.headers.get("Range")
        if rng and self.support_ranges:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(body) - 1
            chunk = body[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        else:
            chunk = body
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Content-Disposition", 'attachment; filename="test data.bin"')
        self.end_headers()
        if self.slow:
            for i in range(0, len(chunk), 16 * 1024):
                self.wfile.write(chunk[i:i + 16 * 1024])
                time.sleep(0.05)
        else:
            self.wfile.write(chunk)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def url(self):
        return f"http://127.0.0.1:{self.port}/file"

    def test_segmented_download_matches(self):
        with tempfile.TemporaryDirectory() as d:
            job = core.DownloadJob(self.url(), d, connections=8)
            job.start()
            job.wait(60)
            self.assertEqual(job.status, "completed", job.error)
            self.assertEqual(job.filename, "test data.bin")
            with open(job.path, "rb") as f:
                self.assertEqual(f.read(), DATA)
            self.assertFalse(os.path.exists(job.part_path))
            self.assertFalse(os.path.exists(job.state_path))
            self.assertGreater(len(job.segments), 1)

    def test_pause_then_resume(self):
        Handler.slow = True
        try:
            with tempfile.TemporaryDirectory() as d:
                job = core.DownloadJob(self.url(), d, connections=4)
                job.start()
                time.sleep(0.6)
                job.pause()
                job.wait(30)
                self.assertEqual(job.status, "paused")
                self.assertGreater(job.downloaded, 0)
                self.assertLess(job.downloaded, len(DATA))

                # محاكاة إعادة تشغيل البرنامج: تحميل الحالة من الملف
                restored = core.DownloadJob.from_dict(job.to_dict())
                self.assertEqual(restored.status, "paused")
                restored.start()
                restored.wait(60)
                self.assertEqual(restored.status, "completed", restored.error)
                with open(restored.path, "rb") as f:
                    self.assertEqual(f.read(), DATA)
        finally:
            Handler.slow = False

    def test_no_range_support_falls_back_to_single_stream(self):
        Handler.support_ranges = False
        try:
            with tempfile.TemporaryDirectory() as d:
                job = core.DownloadJob(self.url(), d, connections=8)
                job.start()
                job.wait(60)
                self.assertEqual(job.status, "completed", job.error)
                self.assertEqual(len(job.segments), 1)
                with open(job.path, "rb") as f:
                    self.assertEqual(f.read(), DATA)
        finally:
            Handler.support_ranges = True

    def test_unique_name_when_file_exists(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "test data.bin"), "wb").close()
            job = core.DownloadJob(self.url(), d, connections=2)
            job.start()
            job.wait(60)
            self.assertEqual(job.filename, "test data (1).bin")
            self.assertEqual(job.status, "completed", job.error)

    def test_http_error_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            job = core.DownloadJob("http://127.0.0.1:1/x", d)  # منفذ مغلق
            job.start()
            job.wait(60)
            self.assertEqual(job.status, "error")
            self.assertTrue(job.error)


if __name__ == "__main__":
    unittest.main()
