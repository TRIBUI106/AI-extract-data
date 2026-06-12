# Batch First-Page Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm button "Scan trang đầu" cho phép chọn nhiều PDF, OCR trang đầu mỗi file, extract 7 metadata fields, hiển thị kết quả dạng bảng real-time trong tab mới, export CSV/Excel.

**Architecture:** Thêm code path song song không đụng workflow OCR hiện tại. `scan_first_page()` mới trong `extraction_pipeline.py` → `BatchScanWorker` QThread trong `main_window.py` → Tab "Kết quả Batch" mới trong `output_panel.py`. Button kích hoạt từ `control_panel.py`. Dialog confirm trong `dialogs.py`.

**Tech Stack:** PySide6 (QThread, Signal, QTableWidget, QProgressBar, QFileDialog), openpyxl (Excel export), csv stdlib, existing field_extractor + file_handler + paddle_ocr_service/ollama_service.

---

## File Map

| File | Thay đổi |
|------|----------|
| `requirements.txt` | Thêm `openpyxl` |
| `src/extraction_pipeline.py` | Thêm `scan_first_page()` |
| `src/ui/dialogs.py` | Thêm `ConfirmBatchDialog` |
| `src/ui/output_panel.py` | Thêm `BatchResultsPanel` + tab index 3 |
| `src/ui/control_panel.py` | Thêm `btn_scan_first_page` + signal |
| `src/ui/main_window.py` | Thêm `BatchScanWorker` + wire signals |

---

## Task 1: Add openpyxl to requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add openpyxl**

Open `requirements.txt` and append after the `sentencepiece` line:

```
openpyxl==3.1.5
```

- [ ] **Step 2: Verify install**

```bash
pip install openpyxl==3.1.5
```

Expected: `Successfully installed openpyxl-3.1.5` (or already satisfied)

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add openpyxl for Excel export in batch scan"
```

---

## Task 2: Add `scan_first_page()` to extraction_pipeline.py

**Files:**
- Modify: `src/extraction_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_first_page.py`:

```python
import pytest
from unittest.mock import patch, MagicMock

def test_scan_first_page_returns_required_keys():
    """scan_first_page must return dict with filename, fields, raw_text, status."""
    mock_client = MagicMock()

    fake_fields = {
        "tac_gia": "Bộ Y Tế", "the_loai": "Công văn",
        "ngay_thang_nam": "01/01/2024", "trich_yeu": "Về việc...",
        "do_mat": "", "nguoi_ky": "Nguyễn Văn A", "loai_ban": "unknown",
    }

    with patch("extraction_pipeline.file_handler.extract_pdf_page_bytes", return_value=b"PNG"), \
         patch("extraction_pipeline._ocr_image", return_value="raw ocr text"), \
         patch("extraction_pipeline.extract_fields", return_value=fake_fields):

        from extraction_pipeline import scan_first_page
        result = scan_first_page("/fake/path/doc.pdf", mock_client, use_correction=False)

    assert result["status"] == "ok"
    assert result["filename"] == "doc.pdf"
    assert result["raw_text"] == "raw ocr text"
    assert result["fields"]["tac_gia"] == "Bộ Y Tế"
    assert result["error_msg"] is None


def test_scan_first_page_returns_error_on_exception():
    """scan_first_page must return status='error' when PDF read fails."""
    mock_client = MagicMock()

    with patch("extraction_pipeline.file_handler.extract_pdf_page_bytes",
               side_effect=Exception("File not found")):
        from extraction_pipeline import scan_first_page
        result = scan_first_page("/fake/nonexistent.pdf", mock_client)

    assert result["status"] == "error"
    assert result["filename"] == "nonexistent.pdf"
    assert "File not found" in result["error_msg"]
    assert result["fields"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:\Code\AI-extract
python -m pytest tests/test_scan_first_page.py -v
```

Expected: `ImportError` or `AttributeError: module 'extraction_pipeline' has no attribute 'scan_first_page'`

- [ ] **Step 3: Implement `scan_first_page()` in `src/extraction_pipeline.py`**

Add this function after `process_page()` (around line 88), before `process_pdf()`:

```python
def scan_first_page(
    pdf_path: str,
    client: Client,
    use_correction: bool = False,
    use_paddle: bool = True,
) -> dict:
    """
    OCR page 0 of a PDF and extract metadata fields.

    Returns
    -------
    dict with keys:
        filename   : basename of pdf_path
        fields     : dict of extracted fields (empty dict on error)
        raw_text   : raw OCR text (empty string on error)
        status     : "ok" | "error"
        error_msg  : error description string or None
    """
    import os
    filename = os.path.basename(pdf_path)
    empty_result = {
        "filename": filename,
        "fields": {},
        "raw_text": "",
        "status": "error",
        "error_msg": None,
    }

    try:
        import file_handler as _fh
        img_bytes = _fh.extract_pdf_page_bytes(pdf_path, page_index=0)
    except Exception as exc:
        empty_result["error_msg"] = str(exc)
        return empty_result

    try:
        if use_paddle:
            from paddle_ocr_service import PaddleOCRService
            svc = PaddleOCRService.get_instance()
            raw_text = svc.ocr_image(img_bytes)
        else:
            import config as _cfg
            prompt = _cfg.PROMPTS.get(_cfg.DEFAULT_PROMPT, "<|grounding|>OCR this image.")
            raw_text = _ocr_image(img_bytes, client, _cfg.OLLAMA_MODEL, prompt)
    except Exception as exc:
        empty_result["error_msg"] = f"OCR failed: {exc}"
        return empty_result

    if use_correction:
        try:
            from text_corrector import correct_text
            raw_text = correct_text(raw_text)
        except Exception:
            pass  # correction is optional — continue with uncorrected text

    try:
        fields = extract_fields(raw_text, client, model=EXTRACTION_MODEL)
    except Exception as exc:
        empty_result["error_msg"] = f"Field extraction failed: {exc}"
        empty_result["raw_text"] = raw_text
        return empty_result

    return {
        "filename": filename,
        "fields": fields,
        "raw_text": raw_text,
        "status": "ok",
        "error_msg": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scan_first_page.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/extraction_pipeline.py tests/test_scan_first_page.py
git commit -m "feat: add scan_first_page() to extraction_pipeline"
```

---

## Task 3: Add `ConfirmBatchDialog` to dialogs.py

**Files:**
- Modify: `src/ui/dialogs.py`

- [ ] **Step 1: Add import and class**

At the top of `src/ui/dialogs.py`, add `QCheckBox` to the existing import:

```python
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QFormLayout,
                                QSpinBox, QDialogButtonBox, QMessageBox,
                                QCheckBox)
```

Then append this class at the end of the file:

```python
class ConfirmBatchDialog(QDialog):
    """Confirm dialog before batch first-page scan."""

    def __init__(self, file_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Xác nhận Scan Trang Đầu")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)

        info = QLabel(f"Đã chọn <b>{file_count}</b> file PDF.\nApp sẽ OCR trang đầu và trích xuất metadata của từng file.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.chk_correction = QCheckBox("Dùng text correction (chậm hơn, chính xác hơn)")
        self.chk_correction.setChecked(False)
        layout.addWidget(self.chk_correction)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Bắt đầu")
        buttons.button(QDialogButtonBox.Cancel).setText("Huỷ")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def use_correction(self) -> bool:
        return self.chk_correction.isChecked()
```

- [ ] **Step 2: Verify no syntax errors**

```bash
python -c "from src.ui.dialogs import ConfirmBatchDialog; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ui/dialogs.py
git commit -m "feat: add ConfirmBatchDialog for batch scan confirmation"
```

---

## Task 4: Add `BatchResultsPanel` and Tab 3 to output_panel.py

**Files:**
- Modify: `src/ui/output_panel.py`

- [ ] **Step 1: Add imports at top of output_panel.py**

Add `QTableWidget`, `QTableWidgetItem`, `QProgressBar`, `QHeaderView` to the existing QtWidgets import block:

```python
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QPushButton, QLabel, QTextEdit, QMenu,
                               QScrollArea, QFrame, QGridLayout, QApplication,
                               QSizePolicy, QTableWidget, QTableWidgetItem,
                               QProgressBar, QHeaderView, QFileDialog)
```

- [ ] **Step 2: Add `BatchResultsPanel` class**

Insert this class just before the `# ==================== Main Widget ====================` comment (before `class OutputPanel`):

```python
# ==================== Tab 4: Batch Results ====================
BATCH_COLUMNS = ["STT", "Tên file", "Tác giả", "Thể loại", "Ngày", "Người ký", "Độ mật", "Trạng thái"]
BATCH_FIELD_KEYS = ["tac_gia", "the_loai", "ngay_thang_nam", "nguoi_ky", "do_mat"]


class BatchResultsPanel(QWidget):
    """Tab showing real-time batch scan results with CSV/Excel export."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setFormat("Đang scan %v/%m file...")
        self._progress.hide()
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, len(BATCH_COLUMNS))
        self._table.setHorizontalHeaderLabels(BATCH_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.btn_export_csv = QPushButton("Xuất CSV")
        self.btn_export_csv.setFixedHeight(32)
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(self._export_csv)
        btn_bar.addWidget(self.btn_export_csv)

        self.btn_export_excel = QPushButton("Xuất Excel")
        self.btn_export_excel.setFixedHeight(32)
        self.btn_export_excel.setEnabled(False)
        self.btn_export_excel.clicked.connect(self._export_excel)
        btn_bar.addWidget(self.btn_export_excel)

        layout.addLayout(btn_bar)

        self._rows: list[dict] = []  # stored for export

    def start_scan(self, total: int):
        """Call before BatchScanWorker starts."""
        self._table.setRowCount(0)
        self._rows.clear()
        self.btn_export_csv.setEnabled(False)
        self.btn_export_excel.setEnabled(False)
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self._progress.show()

    def append_row(self, result: dict):
        """Append one scan result row. Call from row_ready signal handler."""
        self._rows.append(result)
        row_idx = self._table.rowCount()
        self._table.insertRow(row_idx)

        fields = result.get("fields", {})
        status = result.get("status", "error")

        values = [
            str(row_idx + 1),
            result.get("filename", ""),
            fields.get("tac_gia", "—") or "—",
            fields.get("the_loai", "—") or "—",
            fields.get("ngay_thang_nam", "—") or "—",
            fields.get("nguoi_ky", "—") or "—",
            fields.get("do_mat", "—") or "—",
            "✓ OK" if status == "ok" else f"✗ {result.get('error_msg', 'Lỗi')}",
        ]

        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self._table.setItem(row_idx, col, item)

        self._progress.setValue(row_idx + 1)
        self._table.scrollToBottom()

    def finish_scan(self):
        """Call when BatchScanWorker emits finished."""
        self._progress.hide()
        if self._rows:
            self.btn_export_csv.setEnabled(True)
            self.btn_export_excel.setEnabled(True)

    def _export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Xuất CSV", "batch_results.csv",
                                               "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(BATCH_COLUMNS)
            for i, r in enumerate(self._rows):
                fields = r.get("fields", {})
                writer.writerow([
                    i + 1,
                    r.get("filename", ""),
                    fields.get("tac_gia", ""),
                    fields.get("the_loai", ""),
                    fields.get("ngay_thang_nam", ""),
                    fields.get("nguoi_ky", ""),
                    fields.get("do_mat", ""),
                    "OK" if r.get("status") == "ok" else r.get("error_msg", "Lỗi"),
                ])

    def _export_excel(self):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Lỗi", "Chưa cài openpyxl. Chạy: pip install openpyxl")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Xuất Excel", "batch_results.xlsx",
                                               "Excel Files (*.xlsx)")
        if not path:
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Kết quả Batch"

        header_fill = PatternFill("solid", fgColor="1E293B")
        header_font = Font(bold=True, color="93C5FD")
        ws.append(BATCH_COLUMNS)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for i, r in enumerate(self._rows):
            fields = r.get("fields", {})
            ws.append([
                i + 1,
                r.get("filename", ""),
                fields.get("tac_gia", ""),
                fields.get("the_loai", ""),
                fields.get("ngay_thang_nam", ""),
                fields.get("nguoi_ky", ""),
                fields.get("do_mat", ""),
                "OK" if r.get("status") == "ok" else r.get("error_msg", "Lỗi"),
            ])

        ws.column_dimensions["B"].width = 35
        ws.column_dimensions["C"].width = 25
        ws.column_dimensions["D"].width = 20
        ws.column_dimensions["E"].width = 15
        ws.column_dimensions["F"].width = 25
        wb.save(path)
```

- [ ] **Step 3: Register the tab in `OutputPanel.__init__`**

In `OutputPanel.__init__`, after the line `self.tabs.addTab(self.extracted_panel, "")  # index 2`, add:

```python
        # --- Tab 4: Batch scan results ---
        self.batch_results_panel = BatchResultsPanel()
        self.tabs.addTab(self.batch_results_panel, "Kết quả Batch")  # index 3
        self.tabs.setTabEnabled(3, False)
```

- [ ] **Step 4: Add `update_language` entry for tab 3**

In `OutputPanel.update_language()`, after the line `self.tabs.setTabText(2, t.get("tab_extracted", "Trích xuất"))`, add:

```python
        self.tabs.setTabText(3, t.get("tab_batch", "Kết quả Batch"))
```

- [ ] **Step 5: Verify no syntax errors**

```bash
python -c "import sys; sys.path.insert(0,'src'); from ui.output_panel import BatchResultsPanel; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/ui/output_panel.py
git commit -m "feat: add BatchResultsPanel tab to OutputPanel"
```

---

## Task 5: Add "Scan trang đầu" button to control_panel.py

**Files:**
- Modify: `src/ui/control_panel.py`

- [ ] **Step 1: Add signal to ControlPanel**

In `ControlPanel` class, after the existing signals at line 21-22:

```python
    start_requested = Signal(list)
    stop_requested = Signal()
    batch_scan_requested = Signal(list, bool)  # (pdf_paths, use_correction)
```

- [ ] **Step 2: Add button in `__init__`**

In `ControlPanel.__init__`, after the `run_layout.addWidget(self.btn_stop)` line (around line 108), add:

```python
        self._layout.addLayout(run_layout)

        # === Batch Scan Button ===
        self.btn_scan_first_page = QPushButton("Scan trang đầu")
        self.btn_scan_first_page.setObjectName("btn_scan_first_page")
        self.btn_scan_first_page.setFixedHeight(32)
        self.btn_scan_first_page.clicked.connect(self._on_scan_first_page_click)
        self._layout.addWidget(self.btn_scan_first_page)
```

Remove the existing `self._layout.addLayout(run_layout)` on line 109 (it will be replaced by the block above — just ensure there's only one `addLayout(run_layout)` call).

- [ ] **Step 3: Add click handler**

Add this method to `ControlPanel`, after `on_stop_click`:

```python
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
```

- [ ] **Step 4: Update `update_language` to handle new button**

In `update_language()`, after `self.btn_clear.setText(...)`, add:

```python
        self.btn_scan_first_page.setText(t.get("btn_scan_first_page", "Scan trang đầu"))
```

- [ ] **Step 5: Update `set_processing_state` to disable button while processing**

In `set_processing_state()`, in the `inputs_enabled` block add:

```python
        self.btn_scan_first_page.setEnabled(inputs_enabled)
```

- [ ] **Step 6: Verify no syntax errors**

```bash
python -c "import sys; sys.path.insert(0,'src'); from ui.control_panel import ControlPanel; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/ui/control_panel.py
git commit -m "feat: add Scan trang dau button to ControlPanel"
```

---

## Task 6: Add `BatchScanWorker` and wire signals in main_window.py

**Files:**
- Modify: `src/ui/main_window.py`

- [ ] **Step 1: Add import for `scan_first_page`**

At the top of `src/ui/main_window.py`, after `from ollama_service import ModelUnloadWorker, PreCheckWorker`, add:

```python
from extraction_pipeline import scan_first_page
import config as _cfg
```

- [ ] **Step 2: Add `BatchScanWorker` class**

Add this class just before `class MainWindow`, after `class FieldExtractionWorker`:

```python
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
```

- [ ] **Step 3: Wire `batch_scan_requested` signal in `MainWindow.init_ui()`**

In `init_ui()`, after the line:

```python
        self.control_panel.stop_requested.connect(self.stop_processing)
```

Add:

```python
        self.control_panel.batch_scan_requested.connect(self._on_batch_scan_requested)
```

- [ ] **Step 4: Add `_batch_worker` attribute in `__init__`**

In `MainWindow.__init__`, after `self.corrector_worker = None`, add:

```python
        self._batch_worker = None
```

- [ ] **Step 5: Add batch scan handler methods**

Add these methods to `MainWindow`, after `_on_extraction_finished`:

```python
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
```

- [ ] **Step 6: Verify no syntax errors**

```bash
python -c "import sys; sys.path.insert(0,'src'); from ui.main_window import BatchScanWorker; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/ui/main_window.py
git commit -m "feat: add BatchScanWorker and wire batch scan flow in MainWindow"
```

---

## Task 7: Manual verification

- [ ] **Step 1: Launch app**

```bash
cd D:\Code\AI-extract
python src/main.py
```

- [ ] **Step 2: Test happy path**
  1. Click "Scan trang đầu"
  2. Chọn 2–3 file PDF
  3. Trong ConfirmBatchDialog: để correction OFF → click "Bắt đầu"
  4. Quan sát tab "Kết quả Batch" tự động mở
  5. Verify rows xuất hiện real-time theo từng file hoàn thành
  6. Verify progress bar tiến lên đúng
  7. Sau khi xong: click "Xuất CSV" → mở file, kiểm tra data đúng
  8. Click "Xuất Excel" → mở file, kiểm tra header màu + data đúng

- [ ] **Step 3: Test error handling**
  1. Chọn 1 file PDF bị corrupt hoặc bị khoá
  2. Verify row xuất hiện với Trạng thái "✗ Lỗi" thay vì crash

- [ ] **Step 4: Test workflow cũ không bị ảnh hưởng**
  1. Thêm PDF vào queue bình thường
  2. Click "Bắt đầu xử lý" → verify OCR chạy bình thường
  3. Tab "Kết quả Batch" vẫn còn nếu đã scan trước đó

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete batch first-page scan feature"
```
