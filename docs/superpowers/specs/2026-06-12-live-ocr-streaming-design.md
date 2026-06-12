# Design: Live OCR Streaming (B+C)

**Date:** 2026-06-12  
**Scope:** Batch scan first-page flow + single-file OCR flow  
**Goal:** Show log status + OCR text blocks in real-time as each file is processed, instead of waiting for all results to appear at once.

---

## Problem

PaddleOCR's `pipeline.predict()` is a blocking call that returns all results at once. Currently:
- Batch scan: UI shows nothing until a file completes entirely
- Single OCR: text appears only after full OCR finishes
- No per-stage feedback (loading model, OCR-ing, extracting fields)

---

## Design

### Layer 1 — `paddle_ocr_service.py`: Block-level callback

Add an optional `callback: Callable[[str], None] = None` parameter to `ocr_image_bytes()`.

After PaddleOCR returns its result, instead of assembling all blocks into one string and returning, the function iterates `parsing_res_list` block-by-block and calls `callback(block_text)` for each non-empty block immediately as it's parsed. The full assembled text is still returned as before (no breaking change).

```python
def ocr_image_bytes(img_bytes: bytes, callback=None) -> str:
    ...
    for res in results:
        text = _extract_markdown(res, callback=callback)
    ...

def _extract_markdown(result, callback=None) -> str:
    # in fallback path: call callback(content) per block before appending
    for block in sorted(blocks, ...):
        content = block.get("block_content", "")
        if content and content.strip():
            if callback:
                callback(content + "\n")
            lines.append(content.strip())
    # in markdown path: split on double-newline and emit each paragraph
```

This is the **only change** needed in `paddle_ocr_service.py`.

---

### Layer 2 — `extraction_pipeline.py`: Thread-safe callback threading

`scan_first_page()` receives an optional `ocr_callback: Callable[[str], None] = None` and passes it through to `ocr_image_bytes()`.

No other changes to `extraction_pipeline.py`.

---

### Layer 3 — `BatchScanWorker` in `main_window.py`: New signals

Add two signals to `BatchScanWorker`:

```python
log_message = QSignal(str)    # status log lines: "[1/5] hopdong.pdf — đang OCR..."
stream_chunk = QSignal(str)   # OCR text blocks as they arrive
```

**Per-file flow inside `run()`:**
1. `log_message.emit(f"[{i+1}/{total}] {filename} — đang OCR...")`
2. Create lambda callback → emits `stream_chunk`
3. Call `scan_first_page(..., ocr_callback=callback)`
4. `log_message.emit(f"[{i+1}/{total}] OCR xong ({len} ký tự) — đang extract fields...")`
5. `log_message.emit(f"[{i+1}/{total}] ✓ {filename} hoàn tất")`  (or error message)
6. `row_ready.emit(result)` — unchanged

---

### Layer 4 — `BatchResultsPanel` in `output_panel.py`: Log panel

Add to the top of `BatchResultsPanel` (above the table):

**Status label** (1 line, bold) — always shows current file being processed. Updates in place.

**Log text area** (`QPlainTextEdit`, read-only, ~80px tall, monospace font) — scrollable, appends each `log_message` line. Shows full history of the scan session.

New public methods:
- `append_log(text: str)` — appends to log area + auto-scrolls
- `update_status(text: str)` — updates the 1-line status label

---

### Layer 5 — `main_window.py`: Wire signals to UI

In `_on_batch_scan_requested()`:

```python
self._batch_worker.log_message.connect(self._on_batch_log)
self._batch_worker.stream_chunk.connect(self._on_batch_stream_chunk)
```

New slots:
```python
@Slot(str)
def _on_batch_log(self, text: str):
    self.output_panel.batch_results_panel.append_log(text)
    self.output_panel.batch_results_panel.update_status(text)

@Slot(str)
def _on_batch_stream_chunk(self, text: str):
    # Switch to Raw Text tab temporarily? No — append silently, user can check
    self.output_panel.append_text(text)
```

**Raw Text tab behaviour:**
- When batch scan starts, `append_text(f"\n\n=== {filename} ===\n")` is emitted before each file's stream starts
- OCR blocks stream in as they arrive
- After each file: no separator needed (next file's header provides it)
- Tab is NOT forcibly switched to Raw Text (user stays on Batch Results to see progress)

---

## Data Flow Summary

```
BatchScanWorker.run()
  → log_message signal ──────────────────→ BatchResultsPanel.append_log()
                                         → BatchResultsPanel.update_status()
  → scan_first_page(ocr_callback=fn)
      → ocr_image_bytes(callback=fn)
          → per block: fn(block_text)
              → stream_chunk signal ──────→ OutputPanel.append_text()  [Raw Text tab]
  → row_ready signal ────────────────────→ BatchResultsPanel.append_row()  [unchanged]
```

---

## Files Changed

| File | Change |
|------|--------|
| `src/paddle_ocr_service.py` | Add `callback` param to `ocr_image_bytes()` and `_extract_markdown()` |
| `src/extraction_pipeline.py` | Add `ocr_callback` param to `scan_first_page()`, pass through |
| `src/ui/main_window.py` | Add signals to `BatchScanWorker`, add 2 slots, wire in `_on_batch_scan_requested` |
| `src/ui/output_panel.py` | Add status label + log area to `BatchResultsPanel`, add `append_log()` / `update_status()` |

No new files. No changes to single-file OCR flow (callback defaults to `None` everywhere).

---

## Error Handling

- If `callback` raises inside `ocr_image_bytes()`, it is caught and silently skipped (OCR result unaffected)
- Log messages for errors: `[2/5] ✗ file.pdf — OCR thất bại: <error>`

---

## Testing

- Existing `test_scan_first_page.py` tests unchanged (callback=None path)
- New test: `test_ocr_image_bytes_callback` — mock `pipeline.predict()`, verify callback called per block in order
