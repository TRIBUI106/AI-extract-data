# Live OCR Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream OCR text blocks and status logs in real-time during batch scan — text appears block-by-block as PaddleOCR parses each block, plus per-file status logs in both Raw Text tab and Batch Results tab.

**Architecture:** Add optional `callback` param to `ocr_image_bytes()` and `_extract_markdown()` in `paddle_ocr_service.py`; thread callback through `scan_first_page()` in `extraction_pipeline.py`; add `log_message` + `stream_chunk` signals to `BatchScanWorker`; add status label + log area to `BatchResultsPanel`; wire signals in `main_window.py`.

**Tech Stack:** Python 3, PySide6 (QThread, Signal, Slot), PaddleOCR-VL

---

## File Map

| File | Change |
|------|--------|
| `src/paddle_ocr_service.py` | Add `callback` param to `_extract_markdown()` and `ocr_image_bytes()` |
| `src/extraction_pipeline.py` | Add `ocr_callback` param to `scan_first_page()`, pass to `ocr_image_bytes()` |
| `src/ui/main_window.py` | Add `log_message` + `stream_chunk` signals to `BatchScanWorker`; add 2 slots; wire in `_on_batch_scan_requested` |
| `src/ui/output_panel.py` | Add status label + scrollable log area to `BatchResultsPanel`; add `append_log()` / `update_status()` methods |
| `tests/test_scan_first_page.py` | Add test for callback invocation in `ocr_image_bytes()` |

---

### Task 1: Add block-level callback to `paddle_ocr_service.py`

**Files:**
- Modify: `src/paddle_ocr_service.py`
- Test: `tests/test_scan_first_page.py`

- [ ] **Step 1: Write failing test for callback**

Add to `tests/test_scan_first_page.py`:

```python
def test_ocr_image_bytes_callback_called_per_block(monkeypatch):
    """callback is called once per non-empty block in parsing_res_list."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    fake_block_result = MagicMock()
    fake_block_result.markdown = None  # force fallback path

    fake_json = {
        "parsing_res_list": [
            {"block_order": 0, "block_content": "Block one"},
            {"block_order": 1, "block_content": ""},          # empty — must be skipped
            {"block_order": 2, "block_content": "Block two"},
        ]
    }
    fake_block_result.json = fake_json

    fake_pipeline = MagicMock()
    fake_pipeline.predict.return_value = [fake_block_result]

    import paddle_ocr_service
    monkeypatch.setattr(paddle_ocr_service, "_pipeline_instance", fake_pipeline)

    collected = []
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG" + b"\x00" * 10)
        tmp = f.name

    try:
        import builtins
        real_open = builtins.open
        # patch tempfile so ocr_image_bytes uses our fake tmp
        with patch("paddle_ocr_service.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__.return_value.name = tmp
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            result = paddle_ocr_service.ocr_image_bytes(b"\x89PNG" + b"\x00" * 10, callback=collected.append)
    finally:
        import os; os.unlink(tmp)

    assert collected == ["Block one\n", "Block two\n"]
    assert "Block one" in result
    assert "Block two" in result
```

- [ ] **Step 2: Run test — confirm FAIL**

```
cd D:\Code\AI-extract && python\python.exe -m pytest tests/test_scan_first_page.py::test_ocr_image_bytes_callback_called_per_block -v 2>&1
```

Expected: `FAILED` — `ocr_image_bytes() got unexpected keyword argument 'callback'`

- [ ] **Step 3: Implement callback in `_extract_markdown` and `ocr_image_bytes`**

In `src/paddle_ocr_service.py`, replace:

```python
def _extract_markdown(result) -> str:
```

with:

```python
def _extract_markdown(result, callback=None) -> str:
```

In the fallback path inside `_extract_markdown`, after `content = block.get("block_content", "")`:

```python
        for block in sorted(blocks, key=lambda b: b.get("block_order", 0)):
            content = block.get("block_content", "")
            if content and content.strip():
                if callback:
                    try:
                        callback(content + "\n")
                    except Exception:
                        pass
                lines.append(content.strip())
```

In the markdown path (primary path), after extracting `text`:

```python
    try:
        md = result.markdown
        if isinstance(md, dict):
            text = md.get("markdown_texts", "")
        else:
            text = str(md)
        if text and text.strip():
            if callback:
                for para in text.strip().split("\n\n"):
                    if para.strip():
                        try:
                            callback(para.strip() + "\n\n")
                        except Exception:
                            pass
            return text.strip()
    except Exception:
        pass
```

Change `ocr_image_bytes` signature and pass callback down:

```python
def ocr_image_bytes(img_bytes: bytes, callback=None) -> str:
    ...
        for res in results:
            text = _extract_markdown(res, callback=callback)
            if text:
                page_texts.append(text)
```

- [ ] **Step 4: Run test — confirm PASS**

```
cd D:\Code\AI-extract && python\python.exe -m pytest tests/test_scan_first_page.py::test_ocr_image_bytes_callback_called_per_block -v 2>&1
```

Expected: `PASSED`

- [ ] **Step 5: Run full test suite**

```
cd D:\Code\AI-extract && python\python.exe -m pytest tests/test_scan_first_page.py -v 2>&1
```

Expected: all existing tests still PASS

- [ ] **Step 6: Commit**

```
git add src/paddle_ocr_service.py tests/test_scan_first_page.py
git commit -m "feat: add block-level callback to ocr_image_bytes for live streaming"
```

---

### Task 2: Thread `ocr_callback` through `scan_first_page()`

**Files:**
- Modify: `src/extraction_pipeline.py`

- [ ] **Step 1: Add `ocr_callback` param and pass through**

In `src/extraction_pipeline.py`, change `scan_first_page` signature from:

```python
def scan_first_page(pdf_path, client, use_correction=False, use_paddle=True):
```

to:

```python
def scan_first_page(pdf_path, client, use_correction=False, use_paddle=True, ocr_callback=None):
```

Change the paddle branch to pass callback:

```python
        if use_paddle:
            from paddle_ocr_service import ocr_image_bytes
            raw_text = ocr_image_bytes(img_bytes, callback=ocr_callback)
```

- [ ] **Step 2: Verify existing tests still pass**

```
cd D:\Code\AI-extract && python\python.exe -m pytest tests/test_scan_first_page.py -v 2>&1
```

Expected: all PASS

- [ ] **Step 3: Commit**

```
git add src/extraction_pipeline.py
git commit -m "feat: thread ocr_callback through scan_first_page"
```

---

### Task 3: Add signals to `BatchScanWorker` + per-file log emission

**Files:**
- Modify: `src/ui/main_window.py` (BatchScanWorker class, lines 49–81)

- [ ] **Step 1: Add signals and update `run()` with log + stream emissions**

In `src/ui/main_window.py`, replace the `BatchScanWorker` class:

```python
class BatchScanWorker(QThread):
    """Scans the first page of multiple PDFs sequentially off the UI thread."""
    progress     = QSignal(int, int)   # (current, total)
    row_ready    = QSignal(dict)       # one result dict per file
    finished     = QSignal(bool)       # True if stopped by user
    log_message  = QSignal(str)        # status log lines
    stream_chunk = QSignal(str)        # OCR text blocks as they arrive

    def __init__(self, pdf_paths: list, ollama_client, use_correction: bool):
        super().__init__()
        self._paths = pdf_paths
        self._client = ollama_client
        self._use_correction = use_correction
        import threading
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        total = len(self._paths)
        stopped = False
        for i, path in enumerate(self._paths):
            if self._stop_event.is_set():
                stopped = True
                break

            filename = os.path.basename(path)
            self.log_message.emit(f"[{i+1}/{total}] {filename} — đang OCR...")

            # Callback emits stream_chunk signal for each OCR block
            def _ocr_chunk(text, _sig=self.stream_chunk):
                _sig.emit(text)

            result = scan_first_page(
                path,
                self._client,
                use_correction=self._use_correction,
                use_paddle=_cfg.USE_PADDLE_OCR,
                ocr_callback=_ocr_chunk,
            )

            char_count = len(result.get("raw_text", ""))
            if result.get("status") == "ok":
                self.log_message.emit(
                    f"[{i+1}/{total}] ✓ {filename} hoàn tất ({char_count} ký tự)"
                )
            else:
                err = result.get("error_msg", "lỗi không xác định")
                self.log_message.emit(f"[{i+1}/{total}] ✗ {filename} — {err}")

            self.progress.emit(i + 1, total)
            self.row_ready.emit(result)

        self.finished.emit(stopped)
```

- [ ] **Step 2: Verify app imports without error**

```
cd D:\Code\AI-extract && python\python.exe -c "import sys; sys.path.insert(0,'src'); from ui.main_window import MainWindow; print('OK')" 2>&1
```

Expected: `OK` (PySide6/Qt imports may print warnings — those are fine)

- [ ] **Step 3: Commit**

```
git add src/ui/main_window.py
git commit -m "feat: add log_message and stream_chunk signals to BatchScanWorker"
```

---

### Task 4: Add status label + log area to `BatchResultsPanel`

**Files:**
- Modify: `src/ui/output_panel.py`

First, read the current `BatchResultsPanel.__init__` to see exact layout:

```
Read src/ui/output_panel.py lines 390–450
```

- [ ] **Step 1: Read current BatchResultsPanel layout**

Read `src/ui/output_panel.py` offset=390, limit=80 to understand the current widget structure before editing.

- [ ] **Step 2: Add status label + log area widgets**

After the `QProgressBar` widget (and before the `QTableWidget`), insert:

```python
        # --- status label (1-line, bold, current file) ---
        self._status_label = QLabel("—")
        self._status_label.setStyleSheet("font-weight: bold; padding: 2px 0;")
        layout.addWidget(self._status_label)

        # --- scrollable log area ---
        self._log_area = QPlainTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFixedHeight(80)
        self._log_area.setFont(QFont("Consolas, Courier New, monospace", 9))
        self._log_area.setPlaceholderText("Log scan sẽ hiển thị ở đây...")
        layout.addWidget(self._log_area)
```

- [ ] **Step 3: Add `append_log()` and `update_status()` methods**

Add after the existing `finish_scan()` method:

```python
    def append_log(self, text: str):
        self._log_area.moveCursor(QTextCursor.End)
        self._log_area.insertPlainText(text + "\n")
        self._log_area.moveCursor(QTextCursor.End)

    def update_status(self, text: str):
        self._status_label.setText(text)
```

- [ ] **Step 4: Add `start_scan()` reset for log area**

In `start_scan()`, add:

```python
        self._log_area.clear()
        self._status_label.setText("—")
```

- [ ] **Step 5: Check QTextCursor import**

Confirm `QTextCursor` is already imported at top of `output_panel.py`. If not, add:

```python
from PySide6.QtGui import QTextCursor, QFont
```

- [ ] **Step 6: Commit**

```
git add src/ui/output_panel.py
git commit -m "feat: add status label and log area to BatchResultsPanel"
```

---

### Task 5: Wire signals in `main_window.py` + Raw Text streaming

**Files:**
- Modify: `src/ui/main_window.py` (`_on_batch_scan_requested` and new slots)

- [ ] **Step 1: Wire new signals in `_on_batch_scan_requested`**

In `_on_batch_scan_requested`, after the existing signal connections, add:

```python
        self._batch_worker.log_message.connect(self._on_batch_log)
        self._batch_worker.stream_chunk.connect(self._on_batch_stream_chunk)
```

- [ ] **Step 2: Add file header emission before each file starts**

The `log_message` signal currently fires from inside the worker. To emit the Raw Text file header before stream blocks arrive, connect `log_message` to a slot that also writes headers.

Replace `_on_batch_log` implementation:

```python
    @Slot(str)
    def _on_batch_log(self, text: str):
        self.output_panel.batch_results_panel.append_log(text)
        self.output_panel.batch_results_panel.update_status(text)
        # Write file header to Raw Text tab when a new file starts OCR
        if "— đang OCR..." in text:
            # Extract filename from "[N/M] filename — đang OCR..."
            parts = text.split("] ", 1)
            if len(parts) == 2:
                fname = parts[1].replace(" — đang OCR...", "").strip()
                self.output_panel.append_text(f"\n\n=== {fname} ===\n")

    @Slot(str)
    def _on_batch_stream_chunk(self, text: str):
        self.output_panel.append_text(text)
```

- [ ] **Step 3: Verify app starts without error**

```
cd D:\Code\AI-extract && python\python.exe -c "import sys; sys.path.insert(0,'src'); from ui.main_window import MainWindow; print('OK')" 2>&1
```

Expected: `OK`

- [ ] **Step 4: Run full test suite**

```
cd D:\Code\AI-extract && python\python.exe -m pytest tests/test_scan_first_page.py -v 2>&1
```

Expected: all PASS

- [ ] **Step 5: Commit**

```
git add src/ui/main_window.py
git commit -m "feat: wire log_message and stream_chunk signals to UI panels"
```

---

### Task 6: Smoke test — manual verification

- [ ] **Step 1: Launch app**

```
cd D:\Code\AI-extract && python\python.exe src/main.py
```

- [ ] **Step 2: Verify batch scan live feedback**

1. Click "Scan trang đầu", chọn 2-3 file PDF
2. Confirm batchresults tab hiện: status label cập nhật liên tục, log area có các dòng `[1/N] filename — đang OCR...` và `✓ hoàn tất`
3. Confirm Raw Text tab có header `=== filename ===` và text blocks xuất hiện dần trong quá trình scan

- [ ] **Step 3: Final commit nếu cần fix**

```
git add -u
git commit -m "fix: smoke test corrections for live streaming"
```
