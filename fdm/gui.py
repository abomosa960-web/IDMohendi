"""الواجهة الرسومية (PyQt6)."""
from __future__ import annotations

import os
import secrets

from PyQt6.QtCore import Qt, QDateTime, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from .config import Config
from .manager import DownloadManager

STATUS_TEXT = {
    "queued": "في الانتظار",
    "scheduled": "مجدول",
    "downloading": "جارٍ التحميل",
    "paused": "متوقف",
    "completed": "مكتمل",
    "error": "خطأ",
}
COLUMNS = ["اسم الملف", "الحجم", "التقدم", "السرعة", "الحالة"]


def fmt_size(n: float | None) -> str:
    if n is None:
        return "غير معروف"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_speed(bps: float) -> str:
    return f"{fmt_size(bps)}/s" if bps > 0 else "—"


class AddDialog(QDialog):
    def __init__(self, parent, default_dir: str, default_conns: int, prefill: str = ""):
        super().__init__(parent)
        self.setWindowTitle("إضافة تحميل")
        self.setMinimumWidth(560)

        self.url = QLineEdit(prefill)
        self.url.setPlaceholderText("https://example.com/file.zip")
        self.dir = QLineEdit(default_dir)
        browse = QPushButton("استعراض…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir)
        dir_row.addWidget(browse)

        self.conns = QSpinBox()
        self.conns.setRange(1, 32)
        self.conns.setValue(default_conns)

        self.schedule = QCheckBox("جدولة بدء التحميل")
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.when.setEnabled(False)
        self.schedule.toggled.connect(self.when.setEnabled)

        form = QFormLayout()
        form.addRow("الرابط:", self.url)
        form.addRow("حفظ في:", dir_row)
        form.addRow("عدد الاتصالات:", self.conns)
        form.addRow(self.schedule, self.when)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد الحفظ", self.dir.text())
        if path:
            self.dir.setText(path)

    def _accept(self):
        if not self.url.text().strip().lower().startswith(("http://", "https://")):
            QMessageBox.warning(self, "رابط غير صحيح", "اكتب رابطاً يبدأ بـ http:// أو https://")
            return
        self.accept()

    def values(self):
        start_at = self.when.dateTime().toSecsSinceEpoch() if self.schedule.isChecked() else None
        return self.url.text().strip(), self.dir.text().strip(), self.conns.value(), start_at


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("الإعدادات")
        self.setMinimumWidth(560)

        self.dir = QLineEdit(cfg.download_dir)
        browse = QPushButton("استعراض…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir)
        dir_row.addWidget(browse)

        self.max_active = QSpinBox()
        self.max_active.setRange(1, 10)
        self.max_active.setValue(cfg.max_active)

        self.connections = QSpinBox()
        self.connections.setRange(1, 32)
        self.connections.setValue(cfg.connections)

        self.integration = QCheckBox("تفعيل التكامل مع المتصفح")
        self.integration.setChecked(cfg.integration_enabled)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(cfg.integration_port)

        self.token = QLineEdit(cfg.integration_token)
        self.token.setReadOnly(True)
        copy_btn = QPushButton("نسخ")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.token.text()))
        regen_btn = QPushButton("توليد توكن جديد")
        regen_btn.clicked.connect(self._regen_token)
        token_row = QHBoxLayout()
        token_row.addWidget(self.token)
        token_row.addWidget(copy_btn)
        token_row.addWidget(regen_btn)

        form = QFormLayout()
        form.addRow("مجلد التحميل الافتراضي:", dir_row)
        form.addRow("أقصى عدد تحميلات متزامنة:", self.max_active)
        form.addRow("الاتصالات الافتراضية لكل ملف:", self.connections)
        form.addRow(self.integration)
        form.addRow("منفذ الخادم المحلي:", self.port)
        form.addRow("توكن الإضافة:", token_row)

        note = QLabel("تغيير المنفذ أو التفعيل يحتاج إعادة تشغيل البرنامج.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد التحميل", self.dir.text())
        if path:
            self.dir.setText(path)

    def _regen_token(self):
        self.token.setText(secrets.token_urlsafe(24))

    def _save(self):
        self.cfg.download_dir = self.dir.text().strip()
        self.cfg.max_active = self.max_active.value()
        self.cfg.connections = self.connections.value()
        self.cfg.integration_enabled = self.integration.isChecked()
        self.cfg.integration_port = self.port.value()
        self.cfg.integration_token = self.token.text()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, manager: DownloadManager, cfg: Config, data_dir: str):
        super().__init__()
        self.manager = manager
        self.cfg = cfg
        self.data_dir = data_dir
        self.row_ids: list[str] = []

        self.setWindowTitle("FreeDM - مدير التحميل")
        self.resize(980, 560)

        toolbar = QToolBar("الأدوات")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        actions = [
            ("إضافة رابط", self.add_download),
            ("استئناف", self.resume_selected),
            ("إيقاف", self.pause_selected),
            ("متابعة الكل", self.manager.retry_all_paused),
            ("إيقاف الكل", self.pause_all),
            ("حذف", self.remove_selected),
            ("فتح المجلد", self.open_folder),
            ("الإعدادات", self.open_settings),
        ]
        for text, slot in actions:
            act = toolbar.addAction(text)
            act.triggered.connect(slot)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.open_selected_file)
        self.setCentralWidget(self.table)

        self.statusBar().showMessage("جاهز")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

        self.refresh()

    # ----- عرض القائمة -----
    def refresh(self):
        jobs = sorted(self.manager.jobs.values(), key=lambda j: j.created)
        ids = [j.id for j in jobs]
        selected = self._selected_id()

        if ids != self.row_ids:
            self.table.setRowCount(len(jobs))
            self.row_ids = ids
            for r in range(len(jobs)):
                for c in range(len(COLUMNS)):
                    if c != 2:
                        self.table.setItem(r, c, QTableWidgetItem())
                bar = QProgressBar()
                bar.setRange(0, 1000)
                self.table.setCellWidget(r, 2, bar)

        for r, job in enumerate(jobs):
            self.table.item(r, 0).setText(job.filename or job.url)
            self.table.item(r, 1).setText(fmt_size(job.total))
            self.table.item(r, 3).setText(fmt_speed(job.speed) if job.status == "downloading" else "—")
            self.table.item(r, 4).setText(STATUS_TEXT.get(job.status, job.status))
            bar = self.table.cellWidget(r, 2)
            bar.setValue(int(job.progress * 1000))

        if selected in self.row_ids:
            self.table.selectRow(self.row_ids.index(selected))

        active = [j for j in jobs if j.status == "downloading"]
        total_speed = sum(j.speed for j in active)
        self.statusBar().showMessage(
            f"تحميلات نشطة: {len(active)}    السرعة الكلية: {fmt_speed(total_speed)}"
        )

    def _selected_id(self) -> str | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.row_ids):
            return self.row_ids[row]
        return None

    def _selected_job(self):
        job_id = self._selected_id()
        return self.manager.jobs.get(job_id) if job_id else None

    # ----- الإجراءات -----
    def add_download(self):
        clip = QGuiApplication.clipboard().text().strip()
        prefill = clip if clip.lower().startswith(("http://", "https://")) else ""
        dlg = AddDialog(self, self.cfg.download_dir, self.cfg.connections, prefill)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url, folder, conns, start_at = dlg.values()
        self.manager.add(url, connections=conns, start_at=start_at, dest_dir=folder or None)

    def resume_selected(self):
        job = self._selected_job()
        if job:
            self.manager.resume(job.id)

    def pause_selected(self):
        job = self._selected_job()
        if job:
            self.manager.pause(job.id)

    def pause_all(self):
        for job in list(self.manager.jobs.values()):
            if job.status in ("downloading", "queued", "scheduled"):
                self.manager.pause(job.id)

    def remove_selected(self):
        job = self._selected_job()
        if not job:
            return
        box = QMessageBox(self)
        box.setWindowTitle("حذف التحميل")
        box.setText(f"حذف \"{job.filename or job.url}\" من القائمة؟")
        only_list = box.addButton("من القائمة فقط", QMessageBox.ButtonRole.AcceptRole)
        with_file = box.addButton("وحذف الملف أيضاً", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (only_list, with_file):
            self.manager.remove(job.id, delete_file=(clicked is with_file))

    def open_folder(self):
        job = self._selected_job()
        folder = job.dest_dir if job else self.cfg.download_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_selected_file(self):
        job = self._selected_job()
        if job and job.status == "completed" and job.path and os.path.exists(job.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.path))

    def open_settings(self):
        dlg = SettingsDialog(self, self.cfg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.save(self.data_dir)
            self.manager.config = self.cfg
            QMessageBox.information(self, "تم الحفظ", "تم حفظ الإعدادات.")

    def closeEvent(self, event):
        self.timer.stop()
        self.manager.shutdown()
        super().closeEvent(event)
