#!/usr/bin/env python3
"""SEGA ALL.NET Update Manager - 现代化更新包下载 / 解密工具。

- 向支持的游戏 (SDED/SDGB/...) 发送 downloadOrder，获取更新资源列表
- 手动勾选要下载的文件，可逐文件选择是否解密（sega-image-decryption 契约）
- GUI 基于 PySide6 (Qt)：原生高 DPI 渲染（文字清晰）、表格虚拟化（大量资源不拖影）
- 支持打包为单文件 exe (PyInstaller)
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from Crypto.Cipher import AES
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_TITLE = "SEGA ALL.NET Update Manager"
APP_VERSION = "2.1.0"
HEADER_SIZE = 0x200000
BLOCK_SIZE = 0x1000
DL_WORKERS = 8  # 多线程分段下载的并发连接数（对抗单连接限速，实测 8 连接 ≈ 7.4 倍）
ZERO_IV = bytes(16)
TARGET_FS = {
    "exFAT": bytes.fromhex("eb769045584641542020200000000000"),
    "NTFS": bytes.fromhex("eb52904e544653202020200010010000"),
}
FS_AUTO = "自动（OPT/APP=exFAT，PACK=NTFS）"

QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC"; font-size: 13px; }
QMainWindow, QWidget { background: #0F1420; color: #E7ECF3; }
QGroupBox {
    background: #1B2230; border: none; border-radius: 10px;
    margin-top: 16px; padding: 8px 12px 12px 12px;
    font-weight: bold; font-size: 13px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #E7ECF3; }
QLabel { background: transparent; }
QLabel#subtitle { color: #8A94A6; font-weight: normal; }
QLabel#statusLabel { font-weight: bold; }
QLabel#countLabel { color: #8A94A6; font-weight: normal; }
QLabel#legendLabel { color: #8A94A6; font-weight: normal; font-size: 11px; }
QLabel#orderInfoLabel {
    color: #9FB3D1; font-weight: normal; background: #131927;
    border-radius: 6px; padding: 6px 10px;
}
QTableWidget QCheckBox { background: transparent; }
QCheckBox::indicator {
    width: 17px; height: 17px; border: 2px solid #3A4760;
    border-radius: 4px; background: #10151F;
}
QCheckBox::indicator:hover { border-color: #6B7C9E; }
QCheckBox::indicator:checked { background: #3B82F6; border-color: #5B9BFF; }
QCheckBox[role="decrypt"]::indicator:checked { background: #10B981; border-color: #34D399; }
QLineEdit, QComboBox {
    background: #10151F; border: 1px solid #2A3140; border-radius: 6px;
    padding: 5px 8px; color: #E7ECF3;
}
QLineEdit:focus, QComboBox:focus { border-color: #3B82F6; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #1B2230; color: #E7ECF3; selection-background-color: #2C4A75;
}
QPushButton {
    background: #232C3D; color: #D1D9E6; border: none; border-radius: 6px;
    padding: 7px 14px; font-weight: bold;
}
QPushButton:hover { background: #2C374B; }
QPushButton:disabled { background: #1A2130; color: #5A6577; }
QPushButton#accent { background: #3B82F6; color: #FFFFFF; }
QPushButton#accent:hover { background: #2563EB; }
QPushButton#success { background: #10B981; color: #FFFFFF; }
QPushButton#success:hover { background: #059669; }
QPushButton#danger { background: #3B1D24; color: #FCA5A5; }
QPushButton#danger:hover { background: #4A2530; }
QPushButton#big { padding: 10px 14px; font-size: 14px; }
QPushButton#badge { background: #1E3A5F; color: #93C5FD; padding: 3px 8px;
    border-radius: 5px; font-size: 11px; }
/* 可勾选的设置按钮：必须能一眼看出开/关状态 */
QPushButton[checkable="true"] {
    background: #10151F; color: #8A94A6; border: 1px solid #2A3140;
    text-align: left; padding: 7px 10px; font-weight: normal;
}
QPushButton[checkable="true"]:hover { border-color: #3A4760; }
QPushButton[checkable="true"]:checked {
    background: #0E2B22; color: #6EE7B7; border: 1px solid #10B981;
}
QProgressBar {
    background: #10151F; border: none; border-radius: 5px;
    min-height: 10px; max-height: 10px; text-align: center;
}
QProgressBar::chunk { background: #3B82F6; border-radius: 5px; }
QProgressBar#overallBar::chunk { background: #10B981; }
QPlainTextEdit {
    background: #10151F; border: 1px solid #2A3140; border-radius: 8px;
    font-family: "Consolas", "Microsoft YaHei UI"; font-size: 12px; color: #C7D0DD;
}
QTableWidget {
    background: #10151F; alternate-background-color: #131927;
    border: 1px solid #2A3140; border-radius: 8px; gridline-color: #1B2230;
    selection-background-color: #2C4A75; selection-color: #FFFFFF;
}
QTableWidget::item { padding: 4px 6px; }
QTableWidget::item:disabled { color: #5A6577; }
QHeaderView::section {
    background: #161D2B; color: #8A94A6; border: none; border-bottom: 1px solid #2A3140;
    padding: 6px 6px; font-weight: bold; font-size: 12px;
}
QTableCornerButton::section { background: #161D2B; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2C374B; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3A4760; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2C374B; border-radius: 4px; min-width: 30px; }
"""


# ---------------------------------------------------------------------------
# 模块加载（兼容源码运行与 PyInstaller 打包）
# ---------------------------------------------------------------------------

def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def load_module(name: str, candidates: list[Path]):
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    raise RuntimeError(f"找不到模块 {name}，候选路径: {[str(p) for p in candidates]}")


_ROOT = resource_dir()
ORDEROPT = load_module("orderopt_model", [
    _ROOT / "modules" / "orderopt_model.py",
    _ROOT / "allnet-orderopt" / "orderopt-hello-order" / "scripts" / "orderopt_model.py",
])
DECRYPT = load_module("sega_decrypt_to_file", [
    _ROOT / "modules" / "sega_decrypt_to_file.py",
    _ROOT / "sega-image-decryption" / "scripts" / "sega_decrypt_to_file.py",
])
KEYS = load_module("sega_key_iv", [
    _ROOT / "modules" / "sega_key_iv.py",
    _ROOT / "sega-image-decryption" / "scripts" / "sega_key_iv.py",
])

GAME_IDS = sorted(set(ORDEROPT.LITE_CONFIG) | set(ORDEROPT.V1_CONFIG))


def game_protocol(game_id: str) -> str:
    if game_id in ORDEROPT.LITE_CONFIG:
        return "Lite"
    if game_id in ORDEROPT.V1_CONFIG:
        return "V1"
    return "?"


def file_name_from_url(url: str, index: int) -> str:
    name = unquote(Path(urlparse(url).path).name)
    if not name or name in {".", ".."}:
        name = f"resource_{index:03d}.bin"
    return re.sub(r"[<>:\"/\\|?*]", "_", name)


def decrement_version(ver: str) -> str | None:
    """版本号递减一位（1.56 → 1.55，A074 → A073），用于低版本 hello 获取 APP 补丁订单。"""
    v = ver.strip()
    m = re.fullmatch(r"(\d+)\.(\d+)", v)
    if m and int(m.group(2)) > 0:
        minor = int(m.group(2)) - 1
        pad = len(m.group(2)) if m.group(2).startswith("0") else 0
        return f"{m.group(1)}.{minor:0{pad}}" if pad else f"{m.group(1)}.{minor}"
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", v)
    if m and int(m.group(2)) > 0:
        n = int(m.group(2)) - 1
        pad = len(m.group(2)) if m.group(2).startswith("0") else 0
        return f"{m.group(1)}{n:0{pad}}" if pad else f"{m.group(1)}{n}"
    return None


def key_for(file_path: Path, game_id: str) -> tuple[str, str]:
    suffix = file_path.suffix.lower()
    if suffix == ".opt":
        return KEYS.OPT_KEY, "opt"
    if suffix == ".pack":
        return KEYS.PACK_KEY, "pack"
    if suffix == ".app":
        key = KEYS.APP_KEYS.get(game_id.upper())
        if not key:
            raise ValueError(f"解密 APP 暂无 {game_id} 的预置密钥")
        return key, "app"
    raise ValueError(f"不支持解密的文件类型: {file_path.suffix or '无扩展名'}")


def guess_iv(input_path: Path, key_hex: str, fs_name: str) -> str:
    with input_path.open("rb") as handle:
        handle.seek(HEADER_SIZE)
        block = handle.read(16)
    if len(block) != 16:
        raise ValueError("文件不足，无法读取 0x200000 处的首个加密块")
    decrypted = AES.new(bytes.fromhex(key_hex), AES.MODE_CBC, iv=ZERO_IV).decrypt(block)
    return bytes(a ^ b for a, b in zip(decrypted, TARGET_FS[fs_name])).hex().upper()


def extract_opt_image(image_path: Path, dest: Path) -> int:
    """用 FATtools 进程内提取解密后 exFAT 镜像的全部内容到 dest。

    注意：FATtools 1.1.7 对根目录整体拷贝（路径 "/"）有 bug，
    这里改为逐个列出根目录条目再拷贝，可正常工作且兼容打包后的 exe。
    """
    from FATtools import Volume

    dest.mkdir(parents=True, exist_ok=True)
    vol = Volume.vopen(str(image_path), "rb")
    names = vol.listdir()
    for name in names:
        Volume.copy_out(vol, [name], str(dest), None, None, 1 << 20)
    return len(names)


def config_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "sega_update_manager.json"


# ---------------------------------------------------------------------------
# GUI (PySide6)
# ---------------------------------------------------------------------------

class WorkerSignals(QWidget):
    """跨线程信号桥：工作线程 emit，Qt 自动排队投递到主线程。"""

    log = Signal(str)
    status = Signal(str)
    orders = Signal(object)
    file_progress = Signal(int, int, float)  # done_bytes, total_bytes, speed
    decrypt_progress = Signal(int, int)  # done_bytes, total_bytes
    overall = Signal(float)
    done = Signal(str)


class SegaUpdateApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = APP_TITLE
        self.setWindowTitle(APP_TITLE)
        self.resize(1220, 800)
        self.setMinimumSize(1020, 700)

        self.signals = WorkerSignals()
        self.cancel_event = threading.Event()
        self.busy = False
        self._urls: list[str] = []  # 表格行对应的 URL（分栏标题行为空串）
        self._section_rows: set[int] = set()  # 分栏标题行号

        cfg = self._load_config()
        self._cfg_game = cfg.get("game", "SDED")
        self._cfg_version = cfg.get("version", "A074")
        self._cfg_timeout = cfg.get("timeout", "20")
        self._cfg_output = cfg.get("output_dir", str(Path.cwd() / "downloads"))
        self._cfg_dongle = cfg.get("dongle", "")
        self._cfg_fs = cfg.get("fs", FS_AUTO)
        self._cfg_unpack = cfg.get("unpack_default", False)
        self._cfg_extract = cfg.get("extract_opt", True)

        self._build_ui()
        self._connect_signals()
        self._update_protocol()

    # ---- 配置 ---------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            return json.loads(config_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self):
        try:
            config_path().write_text(json.dumps({
                "game": self.game_combo.currentText(),
                "version": self.version_edit.text(),
                "timeout": self.timeout_edit.text(),
                "output_dir": self.output_edit.text(),
                "dongle": self.dongle_edit.text(),
                "fs": self.fs_combo.currentText(),
                "unpack_default": self.unpack_default_check.isChecked(),
                "extract_opt": self.extract_check.isChecked(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def closeEvent(self, event):
        self.cancel_event.set()
        self._save_config()
        super().closeEvent(event)

    # ---- UI ------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # 标题
        title = QLabel("SEGA ALL.NET Update Manager")
        title.setStyleSheet("font-size: 22px; font-weight: bold; background: transparent;")
        root.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # 左列
        left = QVBoxLayout()
        left.setSpacing(12)
        body.addLayout(left, 3)

        # 连接卡片
        conn = QGroupBox("连接")
        conn_layout = QVBoxLayout(conn)
        conn_layout.setSpacing(8)
        fields = QHBoxLayout()
        fields.setSpacing(8)

        game_box = QVBoxLayout()
        game_lbl = QLabel("游戏 ID")
        game_lbl.setObjectName("subtitle")
        game_row = QHBoxLayout()
        game_row.setSpacing(6)
        self.game_combo = QComboBox()
        self.game_combo.addItems(GAME_IDS)
        self.game_combo.setCurrentText(self._cfg_game)
        self.game_combo.setMinimumWidth(130)
        self.protocol_badge = QLabel("")
        self.protocol_badge.setObjectName("badge")
        game_row.addWidget(self.game_combo)
        game_row.addWidget(self.protocol_badge)
        game_box.addWidget(game_lbl)
        game_box.addLayout(game_row)
        fields.addLayout(game_box)

        ver_box = QVBoxLayout()
        ver_lbl = QLabel("版本 (Title Ver)")
        ver_lbl.setObjectName("subtitle")
        self.version_edit = QLineEdit(self._cfg_version)
        self.version_edit.setMinimumWidth(110)
        ver_box.addWidget(ver_lbl)
        ver_box.addWidget(self.version_edit)
        fields.addLayout(ver_box)

        timeout_box = QVBoxLayout()
        timeout_lbl = QLabel("超时 (秒)")
        timeout_lbl.setObjectName("subtitle")
        self.timeout_edit = QLineEdit(self._cfg_timeout)
        self.timeout_edit.setFixedWidth(70)
        timeout_box.addWidget(timeout_lbl)
        timeout_box.addWidget(self.timeout_edit)
        fields.addLayout(timeout_box)

        dongle_box = QVBoxLayout()
        dongle_lbl = QLabel("加密狗号（可选）")
        dongle_lbl.setObjectName("subtitle")
        self.dongle_edit = QLineEdit(self._cfg_dongle)
        self.dongle_edit.setPlaceholderText("A + 10 位字母数字，留空用 keychips.json")
        self.dongle_edit.setMinimumWidth(160)
        dongle_box.addWidget(dongle_lbl)
        dongle_box.addWidget(self.dongle_edit)
        fields.addLayout(dongle_box)

        fields.addStretch(1)
        self.send_btn = QPushButton("发送 downloadOrder")
        self.send_btn.setObjectName("accent")
        self.send_btn.setFixedHeight(32)  # 与下拉框/输入框对齐
        send_box = QVBoxLayout()
        send_box.addStretch(1)  # 占位标签高度，使按钮与输入框底部对齐
        send_box.addWidget(self.send_btn, 0, Qt.AlignBottom)
        fields.addLayout(send_box)
        conn_layout.addLayout(fields)
        left.addWidget(conn)

        # 资源列表卡片
        res = QGroupBox("可用资源")
        res_layout = QVBoxLayout(res)
        res_layout.setSpacing(6)

        self.count_label = QLabel("等待请求…")
        self.count_label.setObjectName("countLabel")
        res_layout.addWidget(self.count_label)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        for text, fn in (
            ("全选下载", lambda: self.set_download_all(True)),
            ("全部不下载", lambda: self.set_download_all(False)),
            ("全部解密", lambda: self.set_unpack_all(True)),
            ("全部不解密", lambda: self.set_unpack_all(False)),
        ):
            btn = QPushButton(text)
            btn.setFixedHeight(28)
            btn.clicked.connect(fn)
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        res_layout.addLayout(toolbar)

        self.order_info = QLabel("")
        self.order_info.setObjectName("orderInfoLabel")
        self.order_info.setWordWrap(True)
        self.order_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        res_layout.addWidget(self.order_info)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["下载", "解密", "类型", "文件名", "URL"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 300)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        res_layout.addWidget(self.table, 1)
        left.addWidget(res, 1)

        # 右列
        right = QVBoxLayout()
        right.setSpacing(12)
        body.addLayout(right, 2)

        # 下载设置
        settings = QGroupBox("下载与解密")
        s = QVBoxLayout(settings)
        s.setSpacing(6)

        out_lbl = QLabel("保存目录")
        out_lbl.setObjectName("subtitle")
        s.addWidget(out_lbl)
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        self.output_edit = QLineEdit(self._cfg_output)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.choose_output)
        self.open_dir_btn = QPushButton("打开")
        self.open_dir_btn.clicked.connect(self.open_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse_btn)
        out_row.addWidget(self.open_dir_btn)
        s.addLayout(out_row)

        fs_lbl = QLabel("文件系统（用于自动猜 IV）")
        fs_lbl.setObjectName("subtitle")
        s.addWidget(fs_lbl)
        self.fs_combo = QComboBox()
        self.fs_combo.addItems([FS_AUTO, "exFAT", "NTFS"])
        self.fs_combo.setCurrentText(self._cfg_fs)
        s.addWidget(self.fs_combo)

        iv_lbl = QLabel("手动 IV（可选，32 位十六进制，覆盖自动猜测）")
        iv_lbl.setObjectName("subtitle")
        s.addWidget(iv_lbl)
        self.manual_iv_edit = QLineEdit()
        self.manual_iv_edit.setPlaceholderText("留空则按文件系统自动猜 IV")
        s.addWidget(self.manual_iv_edit)

        self.unpack_default_check = QPushButton("新资源默认勾选解密")
        self.unpack_default_check.setCheckable(True)
        self.unpack_default_check.setChecked(self._cfg_unpack)
        self.unpack_default_check.clicked.connect(self._save_config)
        s.addWidget(self.unpack_default_check)
        self.extract_check = QPushButton("解密 OPT 后提取镜像内文件（需 FATtools）")
        self.extract_check.setCheckable(True)
        self.extract_check.setChecked(self._cfg_extract)
        self.extract_check.clicked.connect(self._save_config)
        s.addWidget(self.extract_check)

        self.download_btn = QPushButton("下载选中资源")
        self.download_btn.setObjectName("accent")
        self.download_btn.setProperty("class", "big")
        self.download_btn.clicked.connect(self.download_selected)
        self.cancel_btn = QPushButton("取消当前任务")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        s.addWidget(self.download_btn)
        s.addWidget(self.cancel_btn)
        right.addWidget(settings)

        # 进度卡片
        prog = QGroupBox("进度")
        p = QVBoxLayout(prog)
        p.setSpacing(6)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        p.addWidget(self.status_label)
        self.file_bar = QProgressBar()
        self.file_bar.setTextVisible(False)
        self.file_bar.setRange(0, 1000)
        p.addWidget(self.file_bar)
        self.overall_bar = QProgressBar()
        self.overall_bar.setObjectName("overallBar")
        self.overall_bar.setTextVisible(False)
        self.overall_bar.setRange(0, 1000)
        p.addWidget(self.overall_bar)
        right.addWidget(prog)

        # 日志
        logcard = QGroupBox("运行日志")
        lg = QVBoxLayout(logcard)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(4000)
        lg.addWidget(self.log_box)
        right.addWidget(logcard, 1)

    def _connect_signals(self):
        self.send_btn.clicked.connect(self.request_orders)
        self.game_combo.currentTextChanged.connect(self._update_protocol)
        self.game_combo.currentTextChanged.connect(lambda _t: self._save_config())
        self.signals.log.connect(self.log_line)
        self.signals.status.connect(self._set_status)
        self.signals.orders.connect(self.populate_resources)
        self.signals.file_progress.connect(self._on_file_progress)
        self.signals.decrypt_progress.connect(self._on_decrypt_progress)
        self.signals.overall.connect(self.overall_bar.setValue)
        self.signals.done.connect(self._on_done)

    def _update_protocol(self):
        self.protocol_badge.setText(game_protocol(self.game_combo.currentText()))

    # ---- 日志 / 状态 ----------------------------------------------------
    def log_line(self, text: str):
        self.log_box.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")

    def _set_status(self, text: str):
        self.status_label.setText(text)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.send_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def _on_done(self, message: str):
        self._set_busy(False)
        if message:
            self._set_status(message)

    def _on_file_progress(self, done: int, total: int, speed: float):
        self.file_bar.setValue(int(done / total * 1000) if total else 0)
        pct = f" {done / total:.0%}" if total else ""
        sp = f" · {speed / 1048576:.2f} MiB/s" if speed >= 0 else ""
        self._set_status(f"下载中{pct}  {done / 1048576:.1f} MiB{sp}")

    def _on_decrypt_progress(self, done: int, total: int):
        self.file_bar.setValue(int(done / total * 1000) if total else 0)
        pct = f" {done / total:.0%}" if total else ""
        self._set_status(f"解密中{pct}  {done / 1048576:.1f} / {total / 1048576:.1f} MiB")

    # ---- downloadOrder --------------------------------------------------
    def request_orders(self):
        game = self.game_combo.currentText().strip().upper()
        version = self.version_edit.text().strip()
        if not game or not version:
            self.log_line("⚠ 请填写游戏 ID 和版本号")
            return
        try:
            timeout = float(self.timeout_edit.text())
        except ValueError:
            self.log_line("⚠ 超时必须是数字")
            return
        self._save_config()
        self.cancel_event.clear()
        self._set_busy(True)
        self._set_status("正在发送 downloadOrder…")
        dongle = self.dongle_edit.text().strip() or None
        # 无狗号提示：仓库版本不含任何狗号，需在界面填写或提供 keychips.json
        if not dongle and not (ORDEROPT.resolve(game).get("key_chip") or "").strip():
            self.log_line(
                f"⚠ 未配置 {game} 的加密狗号：请在「加密狗号」一栏填写，"
                f"或在程序目录放置 keychips.json，否则服务器可能拒绝请求")
        chip_note = f"，狗号 {dongle}" if dongle else ""
        self.log_line(f"→ downloadOrder: {game} / {version}（{game_protocol(game)} 协议，超时 {timeout:.0f}s{chip_note}）")
        threading.Thread(target=self._request_worker, args=(game, version, timeout, dongle), daemon=True).start()

    def _request_worker(self, game: str, version: str, timeout: float, dongle: str | None):
        try:
            result = ORDEROPT.execute(game, version, timeout, fetch_order_files=True,
                                      dry_run=False, key_chip_override=dongle)
        except Exception as exc:
            self.signals.log.emit(f"✗ 请求异常: {type(exc).__name__}: {exc}")
            self.signals.done.emit("请求失败")
            return
        # 主 hello 未拿到 APP 订单时，用递减一位的版本再 hello 一次
        # （服务器只对低一个版本下发 APP 程序补丁订单，如 SDGB 1.55 → patch 1.56 + option）
        def has_app(orders):
            return any(o.get("type") != "OPT" and not o.get("error") and o.get("install_values")
                       for o in orders)

        if not has_app(result.get("orders", [])):
            alt = decrement_version(version)
            if alt:
                self.signals.log.emit(f"→ 未获得 APP 订单，尝试以版本 {alt} 补充 hello…")
                try:
                    extra = ORDEROPT.execute(game, alt, timeout, fetch_order_files=True,
                                             dry_run=False, key_chip_override=dongle)
                except Exception as exc:
                    extra = None
                    self.signals.log.emit(f"· 补充 hello 失败: {type(exc).__name__}: {exc}")
                if extra and has_app(extra.get("orders", [])):
                    app_orders = [o for o in extra.get("orders", [])
                                  if o.get("type") != "OPT" and not o.get("error")]
                    result["orders"].extend(app_orders)
                    self.signals.log.emit(f"✓ 补充获得 {len(app_orders)} 个 APP 订单（版本 {alt}）")
                elif extra is not None:
                    self.signals.log.emit(f"· 版本 {alt} 也没有 APP 订单")
        self.signals.orders.emit(result)
        self.signals.done.emit("")

    def populate_resources(self, result: dict):
        self.table.setRowCount(0)
        self.table.clearSpans()
        self._urls.clear()
        self._section_rows.clear()

        for item in result.get("diagnostics") or []:
            self.log_line(f"  · {item}")

        # 订单元数据（ORDER_TIME / RELEASE_TIME / 描述），按订单分块竖排
        blocks = []
        for order in result.get("orders", []):
            meta = order.get("meta") or {}
            if order.get("error") or not meta:
                continue
            lines = [f"【{order.get('type', '?')}】"]
            if meta.get("ORDER_TIME"):
                lines.append(f"ORDER_TIME   {meta['ORDER_TIME']}")
            if meta.get("RELEASE_TIME"):
                lines.append(f"RELEASE_TIME {meta['RELEASE_TIME']}")
            if meta.get("GAME_DESC"):
                lines.append(f"描述         {meta['GAME_DESC']}")
            blocks.append("\n".join(lines))
        self.order_info.setText("\n".join(blocks))

        hello = result.get("hello") or {}
        if not hello:
            self.count_label.setText("请求失败")
            return

        rows: list[tuple[str, str, str]] = []
        for order in result.get("orders", []):
            if order.get("error"):
                self.log_line(f"  · 订单 {order.get('type')} 获取失败: {order['error']}")
                continue
            for url in order.get("install_values", []):
                url = url.strip()
                if url:
                    rows.append((url, file_name_from_url(url, len(rows)), order.get("type", "APP")))

        # 按类型分栏：APP（游戏程序）/ OPT（内容数据）
        groups: list[tuple[str, str, list]] = []
        for label, color, want in (
            ("APP 更新（游戏程序）", "#0891B2", "APP"),
            ("OPT 更新（内容数据）", "#8B5CF6", "OPT"),
        ):
            grp = [r for r in rows if r[2] == want]
            if grp:
                groups.append((label, color, grp))
        other = [r for r in rows if r[2] not in ("APP", "OPT")]
        if other:
            groups.append(("其他资源", "#8A94A6", other))

        unpack_default = self.unpack_default_check.isChecked()
        type_colors = {"OPT": QColor("#8B5CF6"), "APP": QColor("#0891B2")}
        self.table.setRowCount(len(rows) + len(groups))
        r = 0
        for label, color, grp in groups:
            # 分栏标题行（跨 5 列，仅展示）
            sec = QTableWidgetItem(label)
            sec.setFlags(Qt.ItemIsEnabled)
            sec.setBackground(QColor("#1A2233"))
            sec.setForeground(QColor(color))
            font = sec.font()
            font.setBold(True)
            sec.setFont(font)
            self.table.setItem(r, 0, sec)
            self.table.setSpan(r, 0, 1, 5)
            self._section_rows.add(r)
            self._urls.append("")
            r += 1
            for url, name, rtype in grp:
                self._urls.append(url)

                # 下载勾选（蓝）
                dl_cb = QCheckBox()
                dl_cb.setProperty("role", "download")
                dl_cb.setToolTip("勾选后下载该文件")
                dl_cb.setChecked(True)
                dl_cb.toggled.connect(lambda checked, row=r: self._on_dl_toggled(row, checked))
                self.table.setCellWidget(r, 0, dl_cb)

                # 解密勾选（绿）：勾选解密会自动勾选下载
                up_cb = QCheckBox()
                up_cb.setProperty("role", "decrypt")
                up_cb.setToolTip("下载后解密解包（自动勾选下载）")
                up_cb.setChecked(unpack_default)
                up_cb.toggled.connect(lambda checked, row=r: self._on_up_toggled(row, checked))
                self.table.setCellWidget(r, 1, up_cb)

                tp = QTableWidgetItem(rtype)
                tp.setFlags(Qt.ItemIsEnabled)
                tp.setForeground(type_colors.get(rtype, QColor("#8A94A6")))
                self.table.setItem(r, 2, tp)

                fn = QTableWidgetItem(name)
                fn.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(r, 3, fn)

                ul = QTableWidgetItem(url)
                ul.setFlags(Qt.ItemIsEnabled)
                ul.setToolTip(url)
                self.table.setItem(r, 4, ul)

                self._update_row_visual(r)
                r += 1
        self._refresh_count()

        if not rows:
            self.log_line("⚠ Hello 成功但没有可用资源：可能该版本已是最新（服务器返回空 uri / null）")
        else:
            parts = [f"{label.split('（')[0]} {len(grp)} 项" for label, _c, grp in groups]
            self.log_line(f"✓ Hello 成功，共 {len(rows)} 个资源（{' · '.join(parts)}）")

    def _dl_check(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, 0)

    def _up_check(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, 1)

    def _on_dl_toggled(self, row: int, checked: bool):
        if not checked:
            # 不下载则不能解密
            up = self._up_check(row)
            if up and up.isChecked():
                up.setChecked(False)
        self._update_row_visual(row)
        self._refresh_count()

    def _on_up_toggled(self, row: int, checked: bool):
        if checked:
            # 解密必须先下载
            dl = self._dl_check(row)
            if dl and not dl.isChecked():
                dl.setChecked(True)

    def _update_row_visual(self, row: int):
        dl = self._dl_check(row)
        up = self._up_check(row)
        dim = dl is not None and not dl.isChecked()  # 未勾选下载 → 整行变暗
        fn = self.table.item(row, 3)
        if fn:
            if not dim and up and up.isChecked():
                fn.setForeground(QColor("#6EE7B7"))  # 下载+解密：文件名标绿
            else:
                fn.setForeground(QColor("#4A5468") if dim else QColor("#E7ECF3"))
        tp = self.table.item(row, 2)
        if tp:
            if dim:
                tp.setForeground(QColor("#3C4354"))
            else:
                tp.setForeground(QColor({"OPT": "#8B5CF6", "APP": "#0891B2"}.get(tp.text(), "#8A94A6")))
        ul = self.table.item(row, 4)
        if ul:
            ul.setForeground(QColor("#3C4354") if dim else QColor("#8A94A6"))

    def _refresh_count(self):
        data_rows = [i for i in range(self.table.rowCount()) if i not in self._section_rows]
        selected = sum(1 for i in data_rows
                       if self._dl_check(i) and self._dl_check(i).isChecked())
        self.count_label.setText(f"共 {len(data_rows)} 项，选中 {selected} 项")

    def set_download_all(self, value: bool):
        for i in range(self.table.rowCount()):
            cb = self._dl_check(i)
            if cb:
                cb.setChecked(value)

    def set_unpack_all(self, value: bool):
        for i in range(self.table.rowCount()):
            cb = self._up_check(i)
            if cb:
                cb.setChecked(value)

    # ---- 下载 / 解密 -----------------------------------------------------
    def choose_output(self):
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if selected:
            self.output_edit.setText(selected)
            self._save_config()

    def open_output(self):
        out = Path(self.output_edit.text()).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        import os

        os.startfile(out)  # noqa: PTH 116 (Windows only)

    def cancel(self):
        self.cancel_event.set()
        self._set_status("正在取消…")

    def download_selected(self):
        rows = []
        for i in range(self.table.rowCount()):
            dl = self._dl_check(i)
            if not dl or not dl.isChecked():
                continue
            up = self._up_check(i)
            rows.append((self._urls[i], self.table.item(i, 3).text(),
                         bool(up and up.isChecked())))
        if not rows:
            self.log_line("⚠ 请至少勾选一个要下载的资源")
            return
        try:
            timeout = float(self.timeout_edit.text())
        except ValueError:
            timeout = 20.0
        out = Path(self.output_edit.text()).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        # 下载 UA 在任务开始时确定：自定义加密狗号优先，否则用该游戏内置狗号
        # （部分游戏的分发服务器会校验狗号 UA，如 SDGA 的 mai2exp 服务器）
        game = self.game_combo.currentText().strip().upper()
        ua = self.dongle_edit.text().strip() or ORDEROPT.resolve(game).get("key_chip") or game
        self._save_config()
        self.cancel_event.clear()
        self._set_busy(True)
        self.overall_bar.setValue(0)
        self.file_bar.setValue(0)
        self._set_status(f"准备下载 {len(rows)} 个资源…")
        self.log_line(f"→ 开始下载 {len(rows)} 个资源 → {out}（UA: {ua}）")
        threading.Thread(target=self._download_worker, args=(rows, out, timeout, ua), daemon=True).start()

    def _download_worker(self, rows: list[tuple[str, str, bool]], out: Path, timeout: float, ua: str):
        out.mkdir(parents=True, exist_ok=True)
        ok, failed = 0, 0
        for index, (url, name, unpack) in enumerate(rows):
            if self.cancel_event.is_set():
                self.signals.log.emit("任务已取消")
                break
            target = out / name
            if target.exists():
                if target.stat().st_size > 0:
                    # 已下载过的文件跳过（可重跑任务补解密/提取，不重复下载）
                    self.signals.log.emit(f"↷ {name} 已存在，跳过下载")
                else:
                    target.unlink()
                    try:
                        self._download_one(url, target, timeout, index, len(rows), ua)
                    except Exception as exc:
                        failed += 1
                        self.signals.log.emit(f"✗ {name}: {type(exc).__name__}: {exc}")
                        continue
            else:
                try:
                    self._download_one(url, target, timeout, index, len(rows), ua)
                except Exception as exc:
                    failed += 1
                    self.signals.log.emit(f"✗ {name}: {type(exc).__name__}: {exc}")
                    continue
            ok += 1
            if unpack:
                try:
                    self._unpack_one(target, out)
                except Exception as exc:
                    failed += 1
                    self.signals.log.emit(f"✗ {name} 解密失败: {type(exc).__name__}: {exc}")
        self.signals.overall.emit(1000)
        self.signals.done.emit(f"完成：成功 {ok} · 失败 {failed}")

    def _download_one(self, url: str, target: Path, timeout: float, index: int, total: int, ua: str):
        self.signals.status.emit(f"[{index + 1}/{total}] 连接 {target.name} …")
        part = target.with_suffix(target.suffix + ".part")
        dl_timeout = max(timeout, 30.0)  # 下载至少 30s 超时，避免慢服务器误判
        last_exc: Exception | None = None
        for attempt in range(1, 4):  # 最多 3 次尝试，支持断点续传
            if self.cancel_event.is_set():
                raise RuntimeError("已取消")
            try:
                self._download_smart(url, part, dl_timeout, index, total, ua)
                part.replace(target)
                self.signals.log.emit(f"✓ 已下载 {target.name}（{target.stat().st_size:,} bytes）")
                return
            except RuntimeError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    self.signals.log.emit(
                        f"⚠ {target.name} 第 {attempt} 次尝试失败: {exc}，3 秒后断点续传重试…")
                    for _ in range(3):
                        if self.cancel_event.is_set():
                            raise RuntimeError("已取消")
                        time.sleep(1)
        raise last_exc  # type: ignore[misc]

    def _download_smart(self, url: str, part: Path, timeout: float, index: int, total: int, ua: str):
        """智能下载：服务器支持 Range 且文件较大时用多线程分段（对抗单连接限速），否则单线程。"""
        size, ranged = 0, False
        try:
            size, ranged = self._probe_download(url, timeout, ua)
        except Exception:
            pass
        if ranged and size > 8 * 1024 * 1024:
            return self._download_parallel(url, part, timeout, index, total, ua, size)
        return self._download_attempt(url, part, timeout, index, total, ua)

    def _probe_download(self, url: str, timeout: float, ua: str) -> tuple[int, bool]:
        """探测文件总大小与 Range 支持（返回 (size, accept_ranges)）。"""
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) == 206:
                cr = resp.headers.get("Content-Range", "")  # 形如 bytes 0-0/123456
                total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else 0
                return total, total > 0
            return int(resp.headers.get("Content-Length") or 0), False

    def _download_parallel(self, url: str, part: Path, timeout: float,
                           index: int, total: int, ua: str, size: int):
        """多线程分段下载：把文件切成 DL_WORKERS 段并发下载，各段独立续传，完成后合并。"""
        n = DL_WORKERS
        # 旧的单线程 .part 残留无法映射到分段，舍弃重来
        if part.exists():
            if part.stat().st_size == size:
                return
            part.unlink()

        bounds = []
        pos = 0
        step = size // n
        for i in range(n):
            end = size - 1 if i == n - 1 else pos + step - 1
            bounds.append((pos, end))
            pos = end + 1
        chunks = [part.with_name(f"{part.name}.{i}") for i in range(n)]

        progress = [0] * n
        stats = {"t": time.monotonic(), "b": 0, "speed": -1.0, "emit": 0.0}
        lock = threading.Lock()
        errors: list[Exception] = []

        def emit_progress():
            with lock:
                done = sum(progress)
                now = time.monotonic()
                if now - stats["t"] >= 0.5:
                    stats["speed"] = (done - stats["b"]) / (now - stats["t"])
                    stats["t"], stats["b"] = now, done
                if now - stats["emit"] < 0.1:  # 限流到约 10Hz
                    return
                stats["emit"] = now
                speed = stats["speed"]
            self.signals.file_progress.emit(done, size, speed)
            self.signals.overall.emit(int((index + done / size) / total * 1000))

        def worker(i: int):
            lo, hi = bounds[i]
            expected = hi - lo + 1
            cpath = chunks[i]
            for attempt in range(1, 4):
                if self.cancel_event.is_set():
                    return
                try:
                    have = cpath.stat().st_size if cpath.exists() else 0
                    if have == expected:
                        with lock:
                            progress[i] = expected
                        emit_progress()
                        return
                    if have > expected:  # 分段文件异常，重新下载该段
                        cpath.unlink()
                        have = 0
                    headers = {"User-Agent": ua, "Range": f"bytes={lo + have}-{hi}"}
                    req = urllib.request.Request(url, headers=headers)
                    base, read = have, 0
                    with urllib.request.urlopen(req, timeout=timeout) as resp, cpath.open("ab") as dst:
                        if getattr(resp, "status", 200) != 206:
                            raise RuntimeError("服务器不支持分段下载（非 206）")
                        while True:
                            if self.cancel_event.is_set():
                                return
                            block = resp.read(256 * 1024)
                            if not block:
                                break
                            dst.write(block)
                            read += len(block)
                            with lock:
                                progress[i] = base + read
                            emit_progress()
                    if cpath.stat().st_size != expected:
                        raise RuntimeError(f"分段 {i} 不完整（{cpath.stat().st_size}/{expected}）")
                    with lock:
                        progress[i] = expected
                    return
                except Exception as exc:
                    if self.cancel_event.is_set():
                        return
                    with lock:
                        errors.append(exc)
                    if attempt < 3:
                        time.sleep(1)
                    else:
                        return

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if self.cancel_event.is_set():
            raise RuntimeError("已取消")
        if errors:
            raise errors[0]
        # 全部分段完成，顺序合并为完整文件
        with part.open("wb") as out:
            for cpath in chunks:
                with cpath.open("rb") as src:
                    while True:
                        block = src.read(1 << 20)
                        if not block:
                            break
                        out.write(block)
        for cpath in chunks:
            cpath.unlink()

    def _download_attempt(self, url: str, part: Path, timeout: float, index: int, total: int, ua: str):
        start = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": ua}
        if start:
            headers["Range"] = f"bytes={start}-"
        req = urllib.request.Request(url, headers=headers)
        last_t, last_b, speed = time.monotonic(), 0, -1
        last_emit = 0.0
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resume = start > 0 and getattr(resp, "status", 200) == 206
            if not resume and start:
                # 服务器不支持断点续传，从头下载
                start = 0
            done = start
            session_base = start  # 本次会话的起始位置（用于测速）
            remaining = int(resp.headers.get("Content-Length") or 0)
            total_size = done + remaining if resume else remaining
            with part.open("ab" if resume else "wb") as dst:
                if resume and done:
                    self.signals.log.emit(f"↻ 断点续传 {part.name}，从 {done / 1048576:.1f} MiB 处继续")
                while True:
                    if self.cancel_event.is_set():
                        raise RuntimeError("已取消")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_t >= 0.5:
                        session_done = done - session_base
                        speed = (session_done - last_b) / (now - last_t)
                        last_t, last_b = now, session_done
                    # 进度事件限流到约 10Hz，避免高频重绘
                    if now - last_emit >= 0.1:
                        last_emit = now
                        self.signals.file_progress.emit(done, total_size, speed)
                        self.signals.overall.emit(
                            int((index + (done / total_size if total_size else 0.5)) / total * 1000))

    def _unpack_one(self, target: Path, out: Path):
        self.signals.status.emit(f"解密中 {target.name} …")
        game = self.game_combo.currentText().strip().upper()
        key_hex, file_type = key_for(target, game)
        fs = self.fs_combo.currentText()
        fs_name = ("NTFS" if file_type == "pack" else "exFAT") if fs.startswith("自动") else fs
        iv = self.manual_iv_edit.text().strip().replace(" ", "")
        if not iv:
            iv = guess_iv(target, key_hex, fs_name)
        if not re.fullmatch(r"[0-9a-fA-F]{32}", iv):
            raise ValueError("IV 必须是 32 位十六进制")
        output = out / f"{target.name}.dec.bin"

        def on_progress(done: int, total: int):
            self.signals.decrypt_progress.emit(done, total)

        written = DECRYPT.decrypt_image_to_file(
            target, output, bytes.fromhex(key_hex), bytes.fromhex(iv),
            HEADER_SIZE, BLOCK_SIZE, True, progress=on_progress,
        )
        self.signals.log.emit(f"✓ 已解密 {target.name} → {output.name}（{written:,} bytes，{fs_name} IV）")
        # OPT 镜像解密后是 exFAT 磁盘镜像，提取其中的实际文件到文件夹
        if file_type == "opt" and self.extract_check.isChecked():
            try:
                self.signals.status.emit(f"提取 {output.name} 镜像内容…")
                extract_dir = out / f"{target.stem}_extracted"
                n = extract_opt_image(output, extract_dir)
                self.signals.log.emit(f"✓ 已提取 {output.name} 内容 → {extract_dir}（{n} 个顶层条目）")
            except ImportError:
                self.signals.log.emit("⚠ 未安装 FATtools，跳过镜像内容提取（仅生成 .dec.bin）")
            except Exception as exc:
                self.signals.log.emit(f"⚠ 提取镜像内容失败: {type(exc).__name__}: {exc}（.dec.bin 已保留）")


def run_selftest() -> int:
    print(f"{APP_TITLE} v{APP_VERSION} self-test")
    print(f"games ({len(GAME_IDS)}): {', '.join(GAME_IDS)}")
    print(f"protocol SDED={game_protocol('SDED')} SDGB={game_protocol('SDGB')}")
    print(f"keys: OPT={KEYS.OPT_KEY[:8]}… PACK={KEYS.PACK_KEY[:8]}… APP[SDGB]={KEYS.APP_KEYS['SDGB'][:8]}…")
    try:
        import FATtools  # noqa: F401

        print("FATtools: available（支持 OPT 镜像内容提取）")
    except ImportError:
        print("FATtools: missing（OPT 解密后仅输出 .dec.bin，不提取内容）")
    print("ok")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return run_selftest()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setApplicationName(APP_TITLE)
    icon_path = resource_dir() / "icon.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = SegaUpdateApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
