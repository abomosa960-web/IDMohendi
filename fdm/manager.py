"""مدير قائمة التحميلات: الانتظار والجدولة وعدد التحميلات المتزامنة."""
from __future__ import annotations

import json
import os
import threading
import time

from .config import Config
from .core import DownloadJob, make_session


class DownloadManager:
    def __init__(self, data_dir: str, config: Config):
        self.data_dir = data_dir
        self.config = config
        self.session = make_session()
        self.jobs: dict[str, DownloadJob] = {}
        self._lock = threading.RLock()
        self._jobs_file = os.path.join(data_dir, "jobs.json")
        self._stop = threading.Event()
        self._load()
        threading.Thread(target=self._loop, name="fdm-scheduler", daemon=True).start()

    # ----- عمليات المستخدم -----
    def add(self, url: str, filename: str | None = None, headers: dict | None = None,
            connections: int | None = None, start_at: float | None = None,
            dest_dir: str | None = None) -> DownloadJob:
        job = DownloadJob(
            url,
            dest_dir or self.config.download_dir,
            connections or self.config.connections,
            filename=filename,
            headers=headers,
            session=self.session,
        )
        if start_at and start_at > time.time():
            job.start_at = start_at
            job.status = "scheduled"
        else:
            job.status = "queued"
        with self._lock:
            self.jobs[job.id] = job
        self._pump()
        self._save()
        return job

    def resume(self, job_id: str) -> None:
        with self._lock:
            job = self.jobs[job_id]
            if job.status in ("paused", "error", "scheduled"):
                job.status = "queued"
        self._pump()

    def pause(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if job.status == "queued" or job.status == "scheduled":
            job.status = "paused"
        else:
            job.pause()

    def remove(self, job_id: str, delete_file: bool = False) -> None:
        with self._lock:
            job = self.jobs.pop(job_id, None)
        if job:
            job.remove_files(delete_target=delete_file)
        self._save()

    def retry_all_paused(self) -> None:
        with self._lock:
            for job in self.jobs.values():
                if job.status in ("paused", "error"):
                    job.status = "queued"
        self._pump()

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            job.pause()
        for job in jobs:
            job.wait(10)
        self._save()

    # ----- الداخلية -----
    def _pump(self) -> None:
        with self._lock:
            active = sum(1 for j in self.jobs.values() if j.is_active())
            for job in sorted(self.jobs.values(), key=lambda j: j.created):
                if active >= self.config.max_active:
                    break
                if job.status == "queued" and not job.is_active():
                    job.start()
                    active += 1

    def _loop(self) -> None:
        while not self._stop.wait(1):
            now = time.time()
            with self._lock:
                for job in self.jobs.values():
                    if job.status == "scheduled" and job.start_at and now >= job.start_at:
                        job.status = "queued"
            self._pump()
            self._save()

    def _save(self) -> None:
        with self._lock:
            data = [j.to_dict() for j in self.jobs.values()]
        tmp = self._jobs_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._jobs_file)
        except OSError:
            pass

    def _load(self) -> None:
        if not os.path.exists(self._jobs_file):
            return
        try:
            with open(self._jobs_file, encoding="utf-8") as f:
                items = json.load(f)
        except (OSError, ValueError):
            return
        for d in items:
            try:
                job = DownloadJob.from_dict(d, self.session)
            except (KeyError, TypeError):
                continue
            self.jobs[job.id] = job
