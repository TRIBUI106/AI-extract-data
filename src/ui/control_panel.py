# src/ui/control_panel.py
# Left sidebar: file queue controls, image viewer, and processing buttons.

import os
import random
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QFileDialog, QLabel,
                               QProgressBar, QMessageBox, QDialog, QSizePolicy)
from PySide6.QtCore import Signal, QTimer, Qt
from PySide6.QtGui import QColor

import config
import file_handler
from .dialogs import PageRangeDialog
from .image_viewer import ImageViewer
from .image_loader import ImageLoaderThread


class ControlPanel(QWidget):
    # Signals to communicate with MainWindow
    start_requested = Signal(list)  # Emitted when Run button clicked
    stop_requested = Signal()       # Emitted when Stop button clicked
    batch_scan_requested = Signal(list, bool)  # (pdf_paths, use_correction)

    # ==================== Initialization ====================
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar_panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)

        # Queue: list of (display_name, filepath, page_index) tuples
        # page_index = -1 for images, 0+ for PDF pages
        self.image_queue = []

        # Stores bounding boxes per image: {index: [(coords, color), ...]}
        self.image_boxes = {}
        self.current_processing_index = -1
        self.t = {}  # Translation dictionary

        self.loader_thread = None  # Background thread for loading images

        # Debounce timer to prevent RAM spikes when scrolling fast
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(200)
        self.debounce_timer.timeout.connect(self._perform_load_image)

        # === Top Row: Add/Clear Buttons ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.btn_add_img = QPushButton("Thêm ảnh")
        self.btn_add_img.setObjectName("btn_add_img")
        self.btn_add_pdf = QPushButton("Thêm PDF")
        self.btn_add_pdf.setObjectName("btn_add_pdf")
        self.btn_clear = QPushButton("Xóa hàng")
        self.btn_clear.setObjectName("btn_clear")

        self.btn_add_img.clicked.connect(self.add_images)
        self.btn_add_pdf.clicked.connect(self.add_pdf)
        self.btn_clear.clicked.connect(self.clear_queue)

        btn_layout.addWidget(self.btn_add_img)
        btn_layout.addWidget(self.btn_add_pdf)
        btn_layout.addWidget(self.btn_clear)
        self._layout.addLayout(btn_layout)

        # === Queue Header with file count badge ===
        queue_header = QHBoxLayout()
        queue_header.setSpacing(6)

        self.lbl_queue = QLabel("Hàng chờ xử lý:")
        self.lbl_queue.setObjectName("lbl_queue_header")

        self.lbl_file_count = QLabel("0")
        self.lbl_file_count.setObjectName("file_count_badge")
        self.lbl_file_count.setAlignment(Qt.AlignCenter)

        queue_header.addWidget(self.lbl_queue)
        queue_header.addWidget(self.lbl_file_count)
        queue_header.addStretch()
        self._layout.addLayout(queue_header)

        # === Queue List ===
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout.addWidget(self.list_widget)

        # === Run/Stop Buttons ===
        run_layout = QHBoxLayout()
        run_layout.setSpacing(4)

        self.btn_run = QPushButton("Bắt đầu xử lý")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setFixedHeight(40)
        self.btn_run.clicked.connect(self.on_start_click)

        self.btn_stop = QPushButton("DỪNG LẠI")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.clicked.connect(self.on_stop_click)

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(False)

        run_layout.addWidget(self.btn_run)
        run_layout.addWidget(self.btn_stop)
        self._layout.addLayout(run_layout)

        # === Batch Scan Button ===
        self.btn_scan_first_page = QPushButton("Scan trang đầu")
        self.btn_scan_first_page.setObjectName("btn_scan_first_page")
        self.btn_scan_first_page.setFixedHeight(32)
        self.btn_scan_first_page.clicked.connect(self._on_scan_first_page_click)
        self._layout.addWidget(self.btn_scan_first_page)

        # === Image Viewer & Navigation Buttons ===
        viewer_layout = QHBoxLayout()
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(2)

        self.image_viewer = ImageViewer()
        self.image_viewer.setMinimumHeight(250)
        self.image_viewer.setMinimumWidth(100)
        viewer_layout.addWidget(self.image_viewer)

        # Right side: Up/Down Arrow Buttons
        arrow_layout = QVBoxLayout()
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        arrow_layout.setSpacing(0)

        self.btn_up = QPushButton("▲")
        self.btn_up.setObjectName("btn_up")
        self.btn_up.setFixedWidth(45)
        self.btn_up.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.btn_up.clicked.connect(self.move_selection_up)

        self.btn_down = QPushButton("▼")
        self.btn_down.setObjectName("btn_down")
        self.btn_down.setFixedWidth(45)
        self.btn_down.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.btn_down.clicked.connect(self.move_selection_down)

        arrow_layout.addWidget(self.btn_up)
        arrow_layout.addWidget(self.btn_down)
        viewer_layout.addLayout(arrow_layout)

        self._layout.addLayout(viewer_layout)

        # === Progress Bar ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Đang xử lý trang %v/%m...")
        self._layout.addWidget(self.progress_bar)

        self.list_widget.currentItemChanged.connect(self.on_queue_item_changed)

    # ==================== State Management ====================
    def update_language(self, t):
        self.t = t
        self.btn_add_img.setText(t.get("btn_add_img", "Thêm ảnh"))
        self.btn_add_pdf.setText(t.get("btn_add_pdf", "Thêm PDF"))
        self.btn_clear.setText(t.get("btn_clear", "Xóa hàng"))
        self.btn_scan_first_page.setText(t.get("btn_scan_first_page", "Scan trang đầu"))
        self.btn_stop.setText(t.get("btn_stop", "DỪNG LẠI"))
        lbl_text = t.get("lbl_queue", "Hàng chờ xử lý:")
        # Strip trailing colon — we render it in the label itself
        self.lbl_queue.setText(lbl_text.rstrip(":") + ":")
        self.update_status()

    def update_status(self):
        count = len(self.image_queue)
        self.lbl_file_count.setText(str(count))

        if "btn_run_ready" in self.t:
            self.btn_run.setText(self.t["btn_run_ready"].format(count))
        else:
            self.btn_run.setText(f"Bắt đầu xử lý ({count})")

        # Only enable Run if not currently processing
        if not self.btn_stop.isEnabled():
            self.btn_run.setEnabled(count > 0)

        # Navigation buttons enabled only if we have more than 1 item
        can_navigate = count > 1
        self.btn_up.setEnabled(can_navigate)
        self.btn_down.setEnabled(can_navigate)

    def set_processing_state(self, is_processing):
        self.btn_run.setEnabled(not is_processing)
        self.btn_stop.setEnabled(is_processing)

        inputs_enabled = not is_processing
        self.btn_add_img.setEnabled(inputs_enabled)
        self.btn_add_pdf.setEnabled(inputs_enabled)
        self.btn_clear.setEnabled(inputs_enabled)
        self.btn_scan_first_page.setEnabled(inputs_enabled)

        if is_processing:
            # Reset progress bar text to processing format
            self.progress_bar.setFormat("Đang xử lý trang %v/%m...")
        else:
            total = self.progress_bar.maximum()
            done = self.progress_bar.value()
            if total > 0 and done == total:
                self.progress_bar.setFormat(f"Hoàn tất {done}/{total} trang")
            elif total > 0:
                self.progress_bar.setFormat(f"Đã dừng ({done}/{total} trang)")

    # ==================== Top Row: Add Images ====================
    def add_images(self):
        ext_filter = "Ảnh (" + " ".join(f"*{ext}" for ext in config.IMAGE_EXTENSIONS) + ")"
        files, _ = QFileDialog.getOpenFileNames(
            self, self.t.get("btn_add_img", "Thêm ảnh"), "", ext_filter)
        self.add_image_files(files)

    def add_image_files(self, filepaths):
        for f in filepaths:
            name = os.path.basename(f)
            self.image_queue.append((name, f, -1))
            self.list_widget.addItem(name)

        if self.list_widget.currentRow() == -1 and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        self.update_status()

    # ==================== Top Row: Add PDF ====================
    def add_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, self.t.get("btn_add_pdf", "Thêm PDF"), "", "PDF Files (*.pdf)")
        self.add_pdf_files(files)

    def add_pdf_files(self, filepaths):
        from page_selector import select_pages
        for f in filepaths:
            try:
                count = file_handler.get_pdf_page_count(f)
                base_name = os.path.basename(f)

                if config.USE_PADDLE_OCR and count >= 2:
                    # Auto-select: page 1 + closing pages (seal/signature)
                    selected = select_pages(f, count)
                else:
                    # Manual range dialog for Ollama mode or single-page PDFs
                    start_p, end_p = 1, count
                    if count >= 2:
                        dlg = PageRangeDialog(base_name, count, self.t, self)
                        if dlg.exec() == QDialog.Accepted:
                            start_p, end_p = dlg.get_range()
                        else:
                            continue
                    selected = list(range(start_p - 1, end_p))

                for i in selected:
                    name = f"{base_name} :P{i+1}"
                    self.image_queue.append((name, f, i))
                    self.list_widget.addItem(name)
            except Exception as e:
                QMessageBox.critical(self, self.t.get("title_error", "Lỗi"), str(e))

        if self.list_widget.currentRow() == -1 and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        self.update_status()

    # ==================== List Navigation ====================
    def move_selection_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.list_widget.setCurrentRow(row - 1)

    def move_selection_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(row + 1)

    # ==================== Clear ====================
    def clear_queue(self):
        self.image_queue.clear()
        self.image_boxes.clear()
        self.list_widget.clear()
        self.image_viewer.scene.clear()
        self.update_status()

    # ==================== Queue List ====================
    def on_queue_item_changed(self, current, previous):
        if not current:
            return

        row = self.list_widget.row(current)
        if row < 0 or row >= len(self.image_queue):
            return

        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.cancel()
            self.loader_thread = None

        self.debounce_timer.stop()
        self.debounce_timer.start()

    def _perform_load_image(self):
        current = self.list_widget.currentItem()
        if not current:
            return

        row = self.list_widget.row(current)
        if row < 0 or row >= len(self.image_queue):
            return

        name, path, page_index = self.image_queue[row]

        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.cancel()

        self.loader_thread = ImageLoaderThread(path, page_index)
        self.loader_thread.image_loaded.connect(lambda b: self.on_image_loaded(b, row))
        self.loader_thread.error_occurred.connect(lambda e: print(f"Error loading image: {e}"))
        self.loader_thread.start()

    def on_image_loaded(self, img_bytes, row):
        if self.list_widget.currentRow() != row:
            return

        try:
            self.image_viewer.display_image(img_bytes)
            if row in self.image_boxes:
                for coords, color in self.image_boxes[row]:
                    self.image_viewer.draw_box(coords, color)
        except Exception as e:
            print(f"Error displaying loaded image: {e}")

    # ==================== Run Button ====================
    def on_start_click(self):
        if not self.image_queue:
            return

        total = len(self.image_queue)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Đang xử lý trang %v/%m...")

        self.start_requested.emit(self.image_queue)

    # ==================== Stop Button ====================
    def on_stop_click(self):
        self.stop_requested.emit()

    def _on_scan_first_page_click(self):
        from PySide6.QtWidgets import QFileDialog, QDialog
        from .dialogs import ConfirmBatchDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn file PDF để scan trang đầu", "", "PDF Files (*.pdf)"
        )
        if not paths:
            return

        dlg = ConfirmBatchDialog(len(paths), self)
        if dlg.exec() != QDialog.Accepted:
            return

        self.batch_scan_requested.emit(paths, dlg.use_correction())

    # ==================== Processing Callbacks ====================
    def on_process_started(self, index):
        if index == 0:
            self.image_boxes.clear()
            current_row = self.list_widget.currentRow()
            if 0 <= current_row < len(self.image_queue):
                _, path, page_index = self.image_queue[current_row]
                if self.loader_thread is not None and self.loader_thread.isRunning():
                    self.loader_thread.cancel()
                self.loader_thread = ImageLoaderThread(path, page_index)
                self.loader_thread.image_loaded.connect(lambda b: self.on_image_loaded(b, current_row))
                self.loader_thread.start()

        self.current_processing_index = index
        if 0 <= index < self.list_widget.count():
            self.list_widget.setCurrentRow(index)

        # Update progress label to show current item name
        total = self.progress_bar.maximum()
        self.progress_bar.setFormat(f"Đang xử lý trang {index + 1}/{total}...")

    def on_stream_chunk(self, text):
        pass  # Output is handled by OutputPanel

    def draw_box(self, coords):
        if self.current_processing_index == -1:
            return

        r = random.randint(0, 200)
        g = random.randint(0, 200)
        b = random.randint(0, 255)
        color = QColor(r, g, b)

        if self.current_processing_index not in self.image_boxes:
            self.image_boxes[self.current_processing_index] = []
        self.image_boxes[self.current_processing_index].append((coords, color))

        if self.list_widget.currentRow() == self.current_processing_index:
            self.image_viewer.draw_box(coords, color)

    # ==================== Progress Bar ====================
    def increment_progress(self):
        self.progress_bar.setValue(self.progress_bar.value() + 1)
        return self.progress_bar.value() == self.progress_bar.maximum()
