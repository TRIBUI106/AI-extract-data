# src/ui/main_window.py
# Main application window — 3-column layout with toolbar and status bar.

import time
import os
import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QSplitter, QComboBox,
                               QMessageBox, QDialog, QDialogButtonBox, QLayout,
                               QFrame, QApplication, QStatusBar)
from PySide6.QtCore import Qt, Slot, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QFontDatabase, QFont

import config
import lang_handler
from ocr_worker import OCRWorker, PaddleOCRWorker
from PySide6.QtCore import QThread, Signal as QSignal
from ollama_service import ModelUnloadWorker, PreCheckWorker
from extraction_pipeline import scan_first_page
import config as _cfg
from text_corrector import TextCorrectorWorker
from .control_panel import ControlPanel
from .output_panel import OutputPanel
from .settings_dialog import SettingsDialog

if config.WIN_TASKBAR_PROGRESS_SUPPORT:
    from win_taskbar import TaskbarProgress


class FieldExtractionWorker(QThread):
    """Runs field_extractor.extract_fields() off the UI thread."""
    finished = QSignal(dict)

    def __init__(self, text: str, ollama_client):
        super().__init__()
        self._text = text
        self._client = ollama_client

    def run(self):
        try:
            from field_extractor import extract_fields
            result = extract_fields(self._text, self._client)
        except Exception as exc:
            print(f"[FieldExtractionWorker] {exc}")
            result = {}
        self.finished.emit(result)


class BatchScanWorker(QThread):
    """Scans the first page of multiple PDFs sequentially off the UI thread."""
    progress = QSignal(int, int)   # (current, total)
    row_ready = QSignal(dict)      # one result dict per file
    finished = QSignal()

    def __init__(self, pdf_paths: list, ollama_client, use_correction: bool):
        super().__init__()
        self._paths = pdf_paths
        self._client = ollama_client
        self._use_correction = use_correction
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        total = len(self._paths)
        for i, path in enumerate(self._paths):
            if self._stop_flag:
                break
            result = scan_first_page(
                path,
                self._client,
                use_correction=self._use_correction,
                use_paddle=_cfg.USE_PADDLE_OCR,
            )
            self.progress.emit(i + 1, total)
            self.row_ready.emit(result)
        self.finished.emit()


def _load_be_vietnam_pro():
    """
    Attempt to load Be Vietnam Pro from bundled font files.
    Falls back gracefully to Noto Sans / system sans-serif if not found.
    Returns the family name to use.
    """
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    font_dir = os.path.join(src_dir, "res", "fonts")

    loaded = False
    if os.path.isdir(font_dir):
        for fname in os.listdir(font_dir):
            if fname.lower().endswith((".ttf", ".otf")):
                path = os.path.join(font_dir, fname)
                fid = QFontDatabase.addApplicationFont(path)
                if fid >= 0:
                    loaded = True

    if loaded:
        return "Be Vietnam Pro"

    # Try Noto Sans as first fallback (also supports Vietnamese)
    families = QFontDatabase.families()
    for candidate in ("Noto Sans", "Segoe UI", "Arial"):
        if candidate in families:
            return candidate

    return ""  # Let Qt pick the system default


class MainWindow(QMainWindow):
    # ==================== Initialization ====================
    def __init__(self, ollama_client):
        super().__init__()
        self.client = ollama_client

        self.setWindowTitle(f"AI Extract ({config.APP_VERSION})")
        self.resize(1280, 720)

        # Apply font
        family = _load_be_vietnam_pro()
        if family:
            app_font = QFont(family, 10)
            QApplication.setFont(app_font)

        # Windows taskbar progress indicator
        self.taskbar = TaskbarProgress() if config.WIN_TASKBAR_PROGRESS_SUPPORT else None

        # Window icon
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "res", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.current_lang_code = lang_handler.get_default_language()
        self.t = lang_handler.load_language(self.current_lang_code)

        self.worker = None # OCR worker thread
        self.unload_worker = None # Model unload worker thread
        self.corrector_worker = None # Text correction worker thread
        self._batch_worker = None
        self.batch_start_time = 0.0
        self._first_show_done = False

        self.init_ui()
        self.apply_language()

    # ==================== Lifecycle ====================
    def showEvent(self, event):
        super().showEvent(event)
        if not self._first_show_done:
            self._first_show_done = True
            QTimer.singleShot(0, self.force_gl_init)

    def force_gl_init(self):
        # HACK: Force WebEngine GL context initialization on startup.
        self.output_panel.tabs.setCurrentIndex(1)
        QTimer.singleShot(0, lambda: self.output_panel.tabs.setCurrentIndex(0))

    # ==================== UI Layout ====================
    def init_ui(self):
        self.setAcceptDrops(True)

        # ── Central widget ──────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Toolbar ─────────────────────────────────────────────────────────
        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("toolbar_widget")
        toolbar_widget.setFixedHeight(48)
        toolbar_layout = QHBoxLayout(toolbar_widget)
        toolbar_layout.setContentsMargins(12, 0, 12, 0)
        toolbar_layout.setSpacing(6)

        # App title
        self.lbl_title = QLabel("AI Extract")
        self.lbl_title.setObjectName("app_title_label")
        toolbar_layout.addWidget(self.lbl_title)

        # Thin vertical separator
        sep1 = QFrame()
        sep1.setObjectName("toolbar_separator")
        sep1.setFrameShape(QFrame.VLine)
        toolbar_layout.addWidget(sep1)

        # About / Settings / Unload — left-aligned toolbar buttons
        self.btn_about = QPushButton()
        self.btn_about.setObjectName("btn_about_toolbar")
        self.btn_about.clicked.connect(self.show_about)
        toolbar_layout.addWidget(self.btn_about)

        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("btn_settings_toolbar")
        self.btn_settings.clicked.connect(self.show_settings)
        toolbar_layout.addWidget(self.btn_settings)

        self.btn_unload = QPushButton()
        self.btn_unload.setObjectName("btn_unload_toolbar")
        self.btn_unload.clicked.connect(self.unload_model)
        toolbar_layout.addWidget(self.btn_unload)

        toolbar_layout.addStretch()

        # Print headers toggle
        self.lbl_print_headers = QLabel()
        toolbar_layout.addWidget(self.lbl_print_headers)

        self.btn_toggle_headers = QPushButton()
        self.btn_toggle_headers.setObjectName("btn_toggle_headers")
        self.btn_toggle_headers.setCheckable(True)
        self.btn_toggle_headers.setChecked(True)
        self.btn_toggle_headers.toggled.connect(self.update_header_toggle_text)
        top_bar.addWidget(self.btn_toggle_headers)

        # Text Correction Toggle
        self.lbl_correction = QLabel()
        top_bar.addWidget(self.lbl_correction)

        self.btn_toggle_correction = QPushButton()
        self.btn_toggle_correction.setObjectName("btn_toggle_headers")
        self.btn_toggle_correction.setCheckable(True)
        self.btn_toggle_correction.setChecked(False)
        self.btn_toggle_correction.toggled.connect(self.update_correction_toggle_text)
        top_bar.addWidget(self.btn_toggle_correction)

        sep2 = QFrame()
        sep2.setObjectName("toolbar_separator")
        sep2.setFrameShape(QFrame.VLine)
        toolbar_layout.addWidget(sep2)

        # Mode selector
        self.lbl_prompt = QLabel()
        toolbar_layout.addWidget(self.lbl_prompt)

        self.combo_prompts = QComboBox()
        self.combo_prompts.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        toolbar_layout.addWidget(self.combo_prompts)

        sep3 = QFrame()
        sep3.setObjectName("toolbar_separator")
        sep3.setFrameShape(QFrame.VLine)
        toolbar_layout.addWidget(sep3)

        # Language selector
        self.lbl_lang = QLabel("Ngôn ngữ:")
        toolbar_layout.addWidget(self.lbl_lang)

        self.combo_lang = QComboBox()
        self.languages = lang_handler.get_available_languages()
        self.combo_lang.addItems(self.languages.keys())
        display_name = next(
            (k for k, v in self.languages.items() if v == self.current_lang_code),
            "Tiếng Việt"
        )
        self.combo_lang.setCurrentText(display_name)
        self.combo_lang.currentTextChanged.connect(self.change_language)
        toolbar_layout.addWidget(self.combo_lang)

        root_layout.addWidget(toolbar_widget)

        # ── 3-column splitter ────────────────────────────────────────────────
        # Column 1 (left)  : ControlPanel — file queue + image viewer
        # Column 2 (center): (image viewer is embedded inside ControlPanel,
        #                      so center column hosts a thin spacer / future use)
        # Column 3 (right) : OutputPanel — tabs with OCR results
        #
        # Because the image viewer lives inside ControlPanel we use a 2-pane
        # splitter for left vs right, and rely on ControlPanel's internal
        # layout for the queue-above / viewer-below split.  A second nested
        # splitter gives users a resizable left:right ratio.

        outer_splitter = QSplitter(Qt.Horizontal)
        outer_splitter.setHandleWidth(2)

        # Left: sidebar / control panel
        self.control_panel = ControlPanel()
        self.control_panel.start_requested.connect(self.initiate_processing)
        self.control_panel.stop_requested.connect(self.stop_processing)
        self.control_panel.batch_scan_requested.connect(self._on_batch_scan_requested)

        # Right: output panel
        self.output_panel = OutputPanel()
        self.output_panel.extract_requested.connect(self._on_extract_requested)

        outer_splitter.addWidget(self.control_panel)
        outer_splitter.addWidget(self.output_panel)

        # Proportions: left ~280 px, right fills the rest
        outer_splitter.setSizes([280, 900])
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)

        root_layout.addWidget(outer_splitter, stretch=1)

        # ── Status bar ───────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(True)
        self.setStatusBar(self.status_bar)

        self.lbl_status = QLabel("Sẵn sàng")
        self.lbl_status.setObjectName("status_bar_label")
        self.status_bar.addWidget(self.lbl_status)

        # ── Drop overlay (hidden by default) ─────────────────────────────────
        self.drop_overlay = QFrame(self)
        self.drop_overlay.setObjectName("drop_overlay")
        self.drop_overlay.hide()

        overlay_layout = QVBoxLayout(self.drop_overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        self.drop_overlay_label = QLabel()
        self.drop_overlay_label.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(self.drop_overlay_label)

    # ==================== Status bar helpers ====================
    def _set_status(self, text: str):
        self.lbl_status.setText(text)

    # ==================== Top Bar: About ====================
    def show_about(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "res", "icon.png")
        icon_url = QUrl.fromLocalFile(icon_path).toString()

        dlg = QDialog(self)
        dlg.setWindowTitle(self.t["about_title"])

        layout = QVBoxLayout(dlg)
        layout.setSizeConstraint(QLayout.SetFixedSize)

        lbl_text = QLabel(self.t["about_text"].format(icon_url, config.APP_VERSION, config.APP_AUTHOR))
        lbl_text.setTextFormat(Qt.RichText)
        layout.addWidget(lbl_text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_gh = buttons.addButton(self.t["btn_about_git"], QDialogButtonBox.ActionRole)

        buttons.accepted.connect(dlg.accept)
        btn_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(config.PROJECT_URL)))

        layout.addWidget(buttons)
        dlg.exec()

    # ==================== Top Bar: Settings ====================
    def show_settings(self):
        dlg = SettingsDialog(self.t, self)
        if dlg.exec():
            from ollama import Client
            self.client = Client(host=config.OLLAMA_HOST)

    # ==================== Top Bar: Unload ====================
    def unload_model(self):
        self.btn_unload.setEnabled(False)
        self.btn_unload.setText(". . .")
        self._set_status("Đang giải phóng Model AI...")

        self.unload_worker = ModelUnloadWorker(self.client)
        self.unload_worker.finished.connect(self.on_unload_finished)
        self.unload_worker.start()

    @Slot(bool, str)
    def on_unload_finished(self, success, message):
        self.btn_unload.setEnabled(True)
        self.btn_unload.setText(self.t["btn_unload"])

        if success:
            self._set_status(self.t.get(message, message))
            QMessageBox.information(self, self.t["title_info"], self.t[message])
        else:
            self._set_status("Lỗi kết nối")
            if "connect" in message.lower() or "connection" in message.lower():
                print(f"on_unload_finished(): {message}", file=sys.stderr)
                QMessageBox.critical(
                    self, self.t["title_error"],
                    self.t["msg_connection_error"].format(config.OLLAMA_HOST)
                )
            else:
                QMessageBox.critical(self, self.t["title_error"], message)

    # ==================== Top Bar: Header toggle / Language ====================
    def update_header_toggle_text(self, checked):
        text = self.t["btn_toggle_headers_on"] if checked else self.t["btn_toggle_headers_off"]
        self.btn_toggle_headers.setText(text)

    def update_correction_toggle_text(self, checked):
        text = self.t.get("btn_toggle_correction_on", "On") if checked else self.t.get("btn_toggle_correction_off", "Off")
        self.btn_toggle_correction.setText(text)

    def change_language(self, lang_name):
        self.current_lang_code = self.languages[lang_name]
        self.t = lang_handler.load_language(self.current_lang_code)
        self.apply_language()

    def apply_language(self):
        # Toolbar
        self.btn_about.setText(self.t["btn_about"])
        self.btn_settings.setText(self.t["btn_settings"])
        self.btn_unload.setText(self.t["btn_unload"])
        self.lbl_print_headers.setText(self.t["lbl_print_headers"])
        self.update_header_toggle_text(self.btn_toggle_headers.isChecked())

        self.lbl_correction.setText(self.t.get("lbl_correction", "Text Correction:"))
        self.update_correction_toggle_text(self.btn_toggle_correction.isChecked())

        self.lbl_prompt.setText(self.t["lbl_prompt"])

        # Prompts dropdown
        current_id = self.combo_prompts.currentData()
        self.combo_prompts.blockSignals(True)
        self.combo_prompts.clear()
        if "prompt_labels" in self.t:
            for pid, label in self.t["prompt_labels"].items():
                self.combo_prompts.addItem(label, pid)

        if current_id:
            index = self.combo_prompts.findData(current_id)
            if index >= 0:
                self.combo_prompts.setCurrentIndex(index)
        else:
            index = self.combo_prompts.findData(config.DEFAULT_PROMPT)
            if index >= 0:
                self.combo_prompts.setCurrentIndex(index)

        self.combo_prompts.blockSignals(False)

        # Child panels
        self.control_panel.update_language(self.t)
        self.output_panel.update_language(self.t)

        # Drop overlay
        self.drop_overlay_label.setText(self.t.get("drop_overlay_text", "Thả tệp tin ở đây"))

        # Status bar
        self._set_status("Sẵn sàng")

    # ==================== Processing State ====================
    def set_processing_state(self, is_processing):
        self.control_panel.set_processing_state(is_processing)
        self.btn_settings.setEnabled(not is_processing)
        self.btn_unload.setEnabled(not is_processing)
        self.combo_lang.setEnabled(not is_processing)
        self.combo_prompts.setEnabled(not is_processing)
        self.btn_toggle_headers.setEnabled(not is_processing)
        self.btn_toggle_correction.setEnabled(not is_processing)

    # ==================== Processing Flow ====================
    @Slot(list)
    def initiate_processing(self, queue):
        self.set_processing_state(True)
        self._pending_queue = queue
        self._pending_pid = self.combo_prompts.currentData()

        if config.USE_PADDLE_OCR:
            # PaddleOCR mode: skip Ollama precheck, start immediately
            prompt_template = config.PROMPTS.get(self._pending_pid, config.PROMPTS[config.DEFAULT_PROMPT])
            self.start_processing(self._pending_queue, prompt_template, config.OLLAMA_MODEL, self._pending_pid)
        else:
            # Ollama OCR mode: check connection + model before starting
            self._set_status("Đang kiểm tra kết nối Ollama...")
            self.precheck_worker = PreCheckWorker(self.client, config.OLLAMA_MODEL)
            self.precheck_worker.finished.connect(self.on_precheck_finished)
            self.precheck_worker.start()

    @Slot(bool, str, str)
    def on_precheck_finished(self, success, error_type, error_msg):
        if not success:
            self.set_processing_state(False)
            self._set_status("Lỗi kết nối — vui lòng kiểm tra Ollama")

            if error_type == 'connection':
                print(f"on_precheck_finished(): {error_msg}", file=sys.stderr)
                QMessageBox.critical(
                    self, self.t["title_error"],
                    self.t["msg_connection_error"].format(config.OLLAMA_HOST)
                )
            elif error_type == 'model':
                print(f"on_precheck_finished(): {error_msg}", file=sys.stderr)
                QMessageBox.critical(
                    self, self.t["title_error"],
                    self.t["msg_model_missing"].format(config.OLLAMA_MODEL, config.OLLAMA_MODEL)
                )
            return

        QMessageBox.information(self, self.t["title_disclaimer"], self.t["msg_loop_disclaimer"])

        prompt_template = config.PROMPTS.get(self._pending_pid, config.PROMPTS[config.DEFAULT_PROMPT])
        self.start_processing(self._pending_queue, prompt_template, config.OLLAMA_MODEL, self._pending_pid)

    def start_processing(self, queue, prompt_template, model_name, prompt_id=None):
        self._user_stopped = False
        self.output_panel.clear()
        self.set_processing_state(True)
        self.batch_start_time = time.time()

        total = len(queue)
        self._set_status(f"Đang xử lý 0/{total} trang...")

        if self.taskbar:
            self.taskbar.set_progress(int(self.winId()), 0, total)

        if config.USE_PADDLE_OCR:
            self.worker = PaddleOCRWorker(queue)
        else:
            self.worker = OCRWorker(self.client, queue, prompt_template, model_name, prompt_id)

        self.worker.stream_chunk.connect(self.output_panel.append_text)
        self.worker.stream_chunk.connect(self.control_panel.on_stream_chunk)
        self.worker.box_detected.connect(self.control_panel.draw_box)
        self.worker.error_occurred.connect(lambda e: self.output_panel.append_text(f"\nERROR: {e}"))

        self.worker.image_started.connect(self.on_image_started)
        self.worker.image_finished.connect(self.on_image_finished)
        self.worker.finished_all.connect(self.on_finished)
        if hasattr(self.worker, 'status_update'):
            self.worker.status_update.connect(self._set_status)

        self.worker.start()

    def stop_processing(self):
        if self.worker and self.worker.isRunning():
            self._user_stopped = True
            self.worker.stop()
            self.output_panel.append_text(f"\n\n=== {self.t['msg_stopped']} ===")
            self._set_status("Đã dừng bởi người dùng")
            self.set_processing_state(False)
            if self.taskbar:
                self.taskbar.stop_progress(int(self.winId()))

    # ==================== Processing Callbacks ====================
    @Slot(str, int)
    def on_image_started(self, display_name, index):
        if self.btn_toggle_headers.isChecked():
            self.output_panel.append_text(f"\n--- {self.t['msg_started'].format(display_name)} ---\n")
        else:
            self.output_panel.append_text(f"\n")

        total = self.control_panel.progress_bar.maximum()
        self._set_status(f"Đang xử lý trang {index + 1}/{total}: {display_name}")

        self.control_panel.on_process_started(index)

    @Slot(str, float)
    def on_image_finished(self, display_name, duration):
        self.control_panel.increment_progress()
        if self.btn_toggle_headers.isChecked():
            self.output_panel.append_text(
                f"\n--- {self.t['msg_elapsed'].format(display_name, duration)} ---\n"
            )
        else:
            self.output_panel.append_text(f"\n")

        done = self.control_panel.progress_bar.value()
        total = self.control_panel.progress_bar.maximum()
        self._set_status(f"Đã xong {done}/{total} trang — {display_name} ({duration:.1f}s)")

        if self.taskbar:
            self.taskbar.set_progress(int(self.winId()), done, total)

    @Slot()
    def on_finished(self):
        # Called when all images have been processed.
        if self.taskbar:
            self.taskbar.stop_progress(int(self.winId()))

        if self.btn_toggle_correction.isChecked():
            self._start_text_correction()
        else:
            self._finalize_output()

    def _start_text_correction(self):
        raw_text = self.output_panel.text_output.toPlainText()
        if not raw_text.strip():
            self._finalize_output()
            return

        self.output_panel.append_text(f"\n\n--- {self.t.get('msg_correction_start', 'Running text correction...')} ---\n")
        self.corrector_worker = TextCorrectorWorker(raw_text)
        self.corrector_worker.correction_done.connect(self._on_correction_done)
        self.corrector_worker.error_occurred.connect(self._on_correction_error)
        self.corrector_worker.progress.connect(self._on_correction_progress)
        self.corrector_worker.start()

    @Slot(str)
    def _on_correction_done(self, corrected_text):
        self.output_panel.set_corrected_text(corrected_text)
        self.output_panel.append_text(f"\n--- {self.t.get('msg_correction_done', 'Text correction complete.')} ---\n")
        self._finalize_output()

    @Slot(str)
    def _on_correction_error(self, error_msg):
        if error_msg == "missing_deps":
            self.output_panel.append_text(f"\n--- {self.t.get('msg_correction_missing_deps', 'Error: torch/transformers not installed. Run: pip install torch transformers')} ---\n")
        else:
            self.output_panel.append_text(f"\n--- Correction error: {error_msg} ---\n")
        self._finalize_output()

    @Slot(int, int)
    def _on_correction_progress(self, current, total):
        label = self.t.get('msg_correction_progress', 'Correcting sentence {}/{}').format(current, total)
        self.output_panel.append_text(f"\r{label}")

    def _finalize_output(self):
        self.set_processing_state(False)
        self.control_panel.update_status()
        self.output_panel.render_fancy_output()

        if self.control_panel.progress_bar.value() == self.control_panel.progress_bar.maximum():
            total_duration = time.time() - self.batch_start_time
            total_str = self.t["msg_total"].format(total_duration)
            QMessageBox.information(
                self, self.t["title_done"], f"{self.t['msg_done']}\n{total_str}"
            )

    @Slot(str)
    def _on_extract_requested(self, text: str):
        self._set_status("Đang trích xuất các trường dữ liệu...")
        self.output_panel.btn_extract.setEnabled(False)
        self._extraction_worker = FieldExtractionWorker(text, self.client)
        self._extraction_worker.finished.connect(self._on_extraction_finished)
        self._extraction_worker.start()

    @Slot(dict)
    def _on_extraction_finished(self, data: dict):
        self.output_panel.btn_extract.setEnabled(True)
        if data:
            self.output_panel.extracted_panel.populate(data)
            self.output_panel.tabs.setTabEnabled(2, True)
            self.output_panel.tabs.setCurrentIndex(2)
        self._set_status("Sẵn sàng")

    @Slot(list, bool)
    def _on_batch_scan_requested(self, pdf_paths: list, use_correction: bool):
        if self._batch_worker and self._batch_worker.isRunning():
            return  # already running

        total = len(pdf_paths)
        self.output_panel.batch_results_panel.start_scan(total)
        self.output_panel.tabs.setTabEnabled(3, True)
        self.output_panel.tabs.setCurrentIndex(3)
        self._set_status(f"Đang scan trang đầu 0/{total} file...")

        self._batch_worker = BatchScanWorker(pdf_paths, self.client, use_correction)
        self._batch_worker.row_ready.connect(self._on_batch_row_ready)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.start()

    @Slot(dict)
    def _on_batch_row_ready(self, result: dict):
        self.output_panel.batch_results_panel.append_row(result)

    @Slot(int, int)
    def _on_batch_progress(self, current: int, total: int):
        self._set_status(f"Đang scan trang đầu {current}/{total} file...")

    @Slot()
    def _on_batch_finished(self):
        self.output_panel.batch_results_panel.finish_scan()
        self._set_status("Scan trang đầu hoàn tất")

    # ==================== Drag and Drop ====================
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'drop_overlay'):
            self.drop_overlay.setGeometry(self.rect())

    def _validate_dropped_files(self, urls):
        images, pdfs, invalid = [], [], []
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in config.IMAGE_EXTENSIONS:
                    images.append(path)
                elif ext == '.pdf':
                    pdfs.append(path)
                else:
                    invalid.append(path)
        return images, pdfs, invalid

    def dragEnterEvent(self, event):
        if self.control_panel.btn_stop.isEnabled():
            event.ignore()
            return

        if event.mimeData().hasUrls():
            images, pdfs, _ = self._validate_dropped_files(event.mimeData().urls())
            if images or pdfs:
                event.acceptProposedAction()
                self.drop_overlay.setGeometry(self.rect())
                self.drop_overlay.show()
                self.drop_overlay.raise_()
                return

        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_overlay.hide()

    def _process_urls(self, urls):
        invalid = []
        image_batch = []
        file_count = 0

        for url in urls:
            if not url.isLocalFile():
                continue

            path = url.toLocalFile()
            ext = os.path.splitext(path)[1].lower()

            if ext in config.IMAGE_EXTENSIONS:
                image_batch.append(path)
                file_count += 1
            elif ext == '.pdf':
                if image_batch:
                    self.control_panel.add_image_files(image_batch)
                    image_batch = []
                self.control_panel.add_pdf_files([path])
                file_count += 1
            else:
                invalid.append(path)

        if image_batch:
            self.control_panel.add_image_files(image_batch)

        if invalid:
            QMessageBox.warning(
                self, self.t["title_disclaimer"], self.t["drop_invalid_files"]
            )

        if file_count > 1:
            QMessageBox.information(
                self, self.t["title_disclaimer"], self.t["drop_order_disclaimer"]
            )

    def dropEvent(self, event):
        self.drop_overlay.hide()
        if not event.mimeData().hasUrls():
            return
        self._process_urls(event.mimeData().urls())
        event.acceptProposedAction()

    # ==================== Keyboard Shortcuts ====================
    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_from_clipboard()
        else:
            super().keyPressEvent(event)

    def paste_from_clipboard(self):
        if self.control_panel.btn_stop.isEnabled():
            return

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasUrls():
            self._process_urls(mime_data.urls())
        elif mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                import tempfile
                from datetime import datetime

                temp_dir = tempfile.gettempdir()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_path = os.path.join(temp_dir, f"local_ai_ocr_clipboard_{timestamp}.png")

                if image.save(temp_path, "PNG"):
                    self.control_panel.add_image_files([temp_path])
