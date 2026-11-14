"""الإعدادات المحفوظة على الجهاز (بدون أي تسجيل)."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "FreeDM")
    os.makedirs(path, exist_ok=True)
    return path


def default_download_dir() -> str:
    path = os.path.join(os.path.expanduser("~"), "Downloads")
    return path if os.path.isdir(path) else os.path.expanduser("~")


@dataclass
class Config:
    download_dir: str = field(default_factory=default_download_dir)
    max_active: int = 3
    connections: int = 8
    integration_enabled: bool = True
    integration_port: int = 8765
    integration_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    @classmethod
    def load(cls, data_dir: str) -> "Config":
        path = os.path.join(data_dir, "config.json")
        cfg = cls()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        if hasattr(cfg, k):
                            setattr(cfg, k, v)
            except (OSError, ValueError):
                pass
        cfg.save(data_dir)   # يحفظ التوكن المولّد أول مرة
        return cfg

    def save(self, data_dir: str) -> None:
        with open(os.path.join(data_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
