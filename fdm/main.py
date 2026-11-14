"""نقطة تشغيل البرنامج."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from .config import Config, app_data_dir
from .gui import MainWindow
from .integration import IntegrationServer
from .manager import DownloadManager


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FreeDM")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    data_dir = app_data_dir()
    cfg = Config.load(data_dir)
    manager = DownloadManager(data_dir, cfg)

    server = None
    if cfg.integration_enabled:
        try:
            server = IntegrationServer(manager, cfg.integration_port, cfg.integration_token)
            server.start()
        except OSError:
            QMessageBox.warning(
                None, "المنفذ مشغول",
                f"المنفذ {cfg.integration_port} مستخدم من برنامج آخر.\n"
                "غيّر المنفذ من الإعدادات ثم أعد تشغيل البرنامج.",
            )

    window = MainWindow(manager, cfg, data_dir)
    window.show()
    code = app.exec()

    if server:
        server.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
