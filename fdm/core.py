"""محرك التحميل: تحميل متعدد الاتصالات مع إيقاف واستئناف وإعادة المحاولة.

لا يحتوي على أي تسجيل أو رقم سري أو فحص تراخيص.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "Mozilla/5.0 FreeDM/1.0"
CHUNK_SIZE = 64 * 1024
MIN_SEGMENT_SIZE = 256 * 1024      # لا نقسّم الملف إلى أجزاء أصغر من هذا
MAX_CONNECTIONS = 32
MAX_RETRIES = 6
TIMEOUT = (15, 30)                 # (اتصال، قراءة)
PART_SUFFIX = ".part"
STATE_SUFFIX = ".fdmstate"


class DownloadError(Exception):
    """خطأ دائم لا فائدة من إعادة المحاولة معه."""


def make_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=64, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:200] or "download"


def filename_from_headers(url: str, headers) -> str:
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cd, re.IGNORECASE)
    if m:
        return safe_filename(unquote(m.group(1).strip('"')))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return safe_filename(m.group(1))
    base = unquote(os.path.basename(urlparse(url).path))
    return safe_filename(base or "download")


def unique_path(path: str) -> str:
    if not os.path.exists(path) and not os.path.exists(path + PART_SUFFIX):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{root} ({i}){ext}"
        if not os.path.exists(candidate) and not os.path.exists(candidate + PART_SUFFIX):
            return candidate
        i += 1


@dataclass
class ProbeResult:
    final_url: str
    total: int | None
    ranges: bool
    filename: str


def probe(session: requests.Session, url: str, headers: dict) -> ProbeResult:
    """يعرف الرابط النهائي وحجم الملف ودعم التحميل الجزئي واسم الملف."""
    req_headers = {"User-Agent": USER_AGENT, "Range": "bytes=0-0", **headers}
    r = session.get(url, headers=req_headers, stream=True, allow_redirects=True, timeout=TIMEOUT)
    try:
        if r.status_code >= 400:
            raise DownloadError(f"HTTP {r.status_code}")
        total, ranges = None, False
        if r.status_code == 206:
            ranges = True
            m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
            if m:
                total = int(m.group(1))
        else:
            cl = r.headers.get("Content-Length", "")
            if cl.isdigit():
                total = int(cl)
        return ProbeResult(r.url, total, ranges, filename_from_headers(r.url, r.headers))
    finally:
        r.close()


@dataclass
class Segment:
    start: int
    end: int | None      # آخر بايت (شامل). None = حجم غير معروف
    done: int = 0        # عدد البايتات المكتوبة في هذا الجزء

    @property
    def position(self) -> int:
        return self.start + self.done

    @property
    def complete(self) -> bool:
        return self.end is not None and self.position > self.end


class DownloadJob:
    def __init__(
        self,
        url: str,
        dest_dir: str,
        connections: int = 8,
        filename: str | None = None,
        headers: dict | None = None,
        job_id: str | None = None,
        session: requests.Session | None = None,
    ):
        import uuid

        self.id = job_id or uuid.uuid4().hex
        self.url = url
        self.final_url = url
        self.dest_dir = dest_dir
        self.filename = filename
        self.connections = max(1, min(int(connections), MAX_CONNECTIONS))
        self.headers = dict(headers or {})
        self.total: int | None = None
        self.ranges = False
        self.segments: list[Segment] = []
        self.status = "queued"          # queued | scheduled | downloading | paused | completed | error
        self.error = ""
        self.speed = 0.0
        self.start_at: float | None = None
        self.created = time.time()
        self.session = session or make_session()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._errors: list[str] = []
        self._thread: threading.Thread | None = None
        self._last_bytes = 0
        self._last_time = 0.0
        self._last_save = 0.0

    # ----- معلومات -----
    @property
    def path(self) -> str | None:
        return os.path.join(self.dest_dir, self.filename) if self.filename else None

    @property
    def part_path(self) -> str | None:
        return self.path + PART_SUFFIX if self.path else None

    @property
    def state_path(self) -> str | None:
        return self.path + STATE_SUFFIX if self.path else None

    @property
    def downloaded(self) -> int:
        with self._lock:
            return sum(s.done for s in self.segments)

    @property
    def progress(self) -> float:
        if not self.total:
            return 1.0 if self.status == "completed" else 0.0
        return min(1.0, self.downloaded / self.total)

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----- التحكم -----
    def start(self) -> None:
        if self.is_active():
            return
        self._stop = threading.Event()
        self._errors = []
        self.error = ""
        self.status = "downloading"
        self._last_time = 0.0
        self._thread = threading.Thread(target=self._run, name=f"job-{self.id}", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def remove_files(self, delete_target: bool = False) -> None:
        self.pause()
        self.wait(10)
        for p in (self.part_path, self.state_path):
            if p and os.path.exists(p):
                os.remove(p)
        if delete_target and self.path and os.path.exists(self.path):
            os.remove(self.path)

    # ----- الحفظ والاستعادة -----
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "final_url": self.final_url,
            "dest_dir": self.dest_dir,
            "filename": self.filename,
            "connections": self.connections,
            # لا نحفظ الكوكيز على القرص أبداً (بيانات دخول حساسة)
            "headers": {k: v for k, v in self.headers.items() if k.lower() != "cookie"},
            "total": self.total,
            "ranges": self.ranges,
            "status": self.status,
            "start_at": self.start_at,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: dict, session: requests.Session | None = None) -> "DownloadJob":
        job = cls(d["url"], d["dest_dir"], d.get("connections", 8), d.get("filename"),
                  d.get("headers"), d["id"], session)
        job.final_url = d.get("final_url", d["url"])
        job.total = d.get("total")
        job.ranges = d.get("ranges", False)
        job.start_at = d.get("start_at")
        job.created = d.get("created", time.time())
        status = d.get("status", "paused")
        job._load_segments()
        job.status = "paused" if status == "downloading" else status
        return job

    def _load_segments(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path) or not os.path.exists(self.part_path or ""):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.segments = [Segment(s, e, d) for s, e, d in data["segments"]]
            self.total = data.get("total", self.total)
            self.final_url = data.get("final_url", self.final_url)
            self.ranges = data.get("ranges", self.ranges)
        except (OSError, ValueError, KeyError):
            self.segments = []   # ملف الحالة تالف: نبدأ من جديد

    def _save_state(self) -> None:
        if not self.state_path or not self.segments:
            return
        with self._lock:
            data = {
                "url": self.url,
                "final_url": self.final_url,
                "total": self.total,
                "ranges": self.ranges,
                "segments": [[s.start, s.end, s.done] for s in self.segments],
            }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.state_path)

    # ----- التنفيذ -----
    def _run(self) -> None:
        try:
            self._prepare()
            self._save_state()
            threads = []
            for seg in self.segments:
                if not seg.complete:
                    t = threading.Thread(target=self._worker, args=(seg,), daemon=True)
                    t.start()
                    threads.append(t)
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
                self._tick()
            self._tick(force_save=True)

            if self._errors:
                self.status = "error"
                self.error = self._errors[0]
                self._save_state()
            elif all(s.complete for s in self.segments):
                os.replace(self.part_path, self.path)
                if os.path.exists(self.state_path):
                    os.remove(self.state_path)
                self.status = "completed"
                self.speed = 0.0
            else:
                self.status = "paused"
                self._save_state()
        except Exception as e:  # noqa: BLE001 - نسجل أي خطأ ونعرضه للمستخدم
            self.status = "error"
            self.error = str(e) or e.__class__.__name__
            self._save_state()

    def _prepare(self) -> None:
        os.makedirs(self.dest_dir, exist_ok=True)
        # الاستئناف ممكن فقط مع دعم الـ Range وحجم معروف، وإلا نبدأ من جديد
        if self.segments and self.ranges and self.total is not None and os.path.exists(self.part_path):
            return  # استئناف من حالة محفوظة

        info = probe(self.session, self.url, self.headers)
        self.final_url = info.final_url
        self.total = info.total
        self.ranges = info.ranges and info.total is not None
        if not self.filename:
            self.filename = os.path.basename(unique_path(os.path.join(self.dest_dir, info.filename)))

        if self.total is None:
            self.segments = [Segment(0, None)]
        elif not self.ranges or self.total < 2 * MIN_SEGMENT_SIZE:
            self.segments = [Segment(0, self.total - 1)]
        else:
            n = min(self.connections, self.total // MIN_SEGMENT_SIZE)
            size = self.total // n
            self.segments = [
                Segment(i * size, self.total - 1 if i == n - 1 else (i + 1) * size - 1)
                for i in range(n)
            ]

        with open(self.part_path, "wb") as f:
            if self.total:
                f.truncate(self.total)   # حجز المساحة مسبقاً

    def _tick(self, force_save: bool = False) -> None:
        now = time.monotonic()
        current = self.downloaded
        if self._last_time:
            dt = now - self._last_time
            if dt > 0:
                self.speed = (current - self._last_bytes) / dt
        self._last_time, self._last_bytes = now, current
        if force_save or now - self._last_save > 2:
            self._save_state()
            self._last_save = now

    def _fail(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)
        self._stop.set()

    def _worker(self, seg: Segment) -> None:
        retries = 0
        while not self._stop.is_set() and not seg.complete:
            before = seg.position
            error: Exception | None = None
            try:
                self._transfer(seg)
            except DownloadError as e:
                self._fail(str(e))
                return
            except (requests.RequestException, OSError) as e:
                error = e

            retries = 0 if seg.position > before else retries + 1
            if retries > MAX_RETRIES:
                self._fail(str(error) if error else "توقف الاتصال مراراً دون تقدم")
                return
            if error or seg.position == before:
                self._stop.wait(min(2 ** retries, 30))

    def _transfer(self, seg: Segment) -> None:
        pos = seg.position
        headers = {"User-Agent": USER_AGENT, **self.headers}
        if self.ranges:
            headers["Range"] = f"bytes={pos}-{'' if seg.end is None else seg.end}"

        with self.session.get(self.final_url, headers=headers, stream=True, timeout=TIMEOUT) as r:
            if self.ranges and r.status_code != 206:
                raise DownloadError(f"السيرفر لا يدعم التحميل المتعدد (HTTP {r.status_code})")
            if r.status_code >= 400:
                raise DownloadError(f"HTTP {r.status_code}")

            with open(self.part_path, "r+b") as f:
                f.seek(pos)
                for chunk in r.iter_content(CHUNK_SIZE):
                    if self._stop.is_set():
                        return
                    if seg.end is not None:
                        chunk = chunk[: max(0, seg.end + 1 - seg.position)]
                    if chunk:
                        f.write(chunk)
                        with self._lock:
                            seg.done += len(chunk)
                    if seg.complete:
                        return

        if seg.end is None and not self._stop.is_set():
            with self._lock:
                seg.end = seg.position - 1   # انتهى الحجم المجهول
