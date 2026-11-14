import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fdm.config import Config  # noqa: E402
from fdm.integration import IntegrationServer  # noqa: E402
from fdm.manager import DownloadManager  # noqa: E402
from tests.test_core import DATA, Handler  # noqa: E402


class ManagerAndApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.file_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.file_port = cls.file_server.server_address[1]
        threading.Thread(target=cls.file_server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.file_server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.dl_dir = os.path.join(self.tmp.name, "dl")
        os.makedirs(self.data_dir)
        self.cfg = Config(download_dir=self.dl_dir, max_active=2, connections=4,
                          integration_port=0, integration_token="secret-token")

    def tearDown(self):
        self.tmp.cleanup()

    def wait_for(self, manager, job_id, status, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if manager.jobs[job_id].status == status:
                return
            time.sleep(0.2)
        self.fail(f"job did not reach {status}: {manager.jobs[job_id].status} {manager.jobs[job_id].error}")

    def test_queue_and_persistence(self):
        manager = DownloadManager(self.data_dir, self.cfg)
        try:
            ids = [manager.add(f"http://127.0.0.1:{self.file_port}/f{i}").id for i in range(3)]
            for jid in ids:
                self.wait_for(manager, jid, "completed")
            with open(os.path.join(self.dl_dir, "test data.bin"), "rb") as f:
                self.assertEqual(f.read(), DATA)
        finally:
            manager.shutdown()

        # إعادة فتح المدير تقرأ القائمة المحفوظة
        again = DownloadManager(self.data_dir, self.cfg)
        try:
            self.assertEqual(len(again.jobs), 3)
            self.assertTrue(all(j.status == "completed" for j in again.jobs.values()))
        finally:
            again.shutdown()

    def test_scheduled_job_waits(self):
        manager = DownloadManager(self.data_dir, self.cfg)
        try:
            job = manager.add(f"http://127.0.0.1:{self.file_port}/s", start_at=time.time() + 3600)
            time.sleep(1.5)
            self.assertEqual(job.status, "scheduled")
            self.assertFalse(job.is_active())
        finally:
            manager.shutdown()

    def test_api_requires_token_and_adds_download(self):
        manager = DownloadManager(self.data_dir, self.cfg)
        api = IntegrationServer(manager, 0, self.cfg.integration_token)
        api.start()
        port = api.httpd.server_address[1]
        url = f"http://127.0.0.1:{port}/add"
        try:
            body = json.dumps({"url": f"http://127.0.0.1:{self.file_port}/api"}).encode()

            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-FreeDM-Token": "wrong"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-FreeDM-Token": "secret-token"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                job_id = json.loads(resp.read())["id"]

            self.wait_for(manager, job_id, "completed")
        finally:
            api.stop()
            manager.shutdown()

    def test_api_rejects_non_http_url(self):
        manager = DownloadManager(self.data_dir, self.cfg)
        api = IntegrationServer(manager, 0, self.cfg.integration_token)
        api.start()
        port = api.httpd.server_address[1]
        try:
            body = json.dumps({"url": "file:///etc/passwd"}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/add", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-FreeDM-Token": "secret-token"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
            self.assertEqual(manager.jobs, {})
        finally:
            api.stop()
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
