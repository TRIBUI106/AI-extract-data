# Batch First-Page Scan — Design Spec

**Date:** 2026-06-12  
**Status:** Approved  

---

## Overview

Thêm tính năng "Scan trang đầu" cho phép user chọn nhiều PDF cùng lúc, app tự động OCR trang đầu của từng file và extract các field metadata, hiển thị kết quả dạng bảng real-time trong tab mới, có thể export CSV/Excel.

---

## Goals

- Batch scan trang đầu nhiều PDF mà không ảnh hưởng workflow OCR đơn lẻ hiện tại
- Kết quả hiển thị real-time theo từng file hoàn thành
- Toggle text correction (mặc định off để ưu tiên tốc độ)
- Export kết quả ra CSV hoặc Excel

---

## Architecture

Thêm code path song song, không thay đổi pipeline hiện tại.

```
control_panel.py        → button + file dialog trigger
extraction_pipeline.py  → scan_first_page() function mới
main_window.py          → BatchScanWorker (QThread) mới
output_panel.py         → Tab "Kết quả Batch" mới
```

---

## Data Flow

```
User click "Scan trang đầu" (control_panel.py)
  ↓
QFileDialog (chọn nhiều PDF, filter *.pdf)
  ↓
ConfirmBatchDialog (số file, toggle correction)
  ↓
BatchScanWorker(QThread).start()
  └── for each pdf_path:
      ├── file_handler.extract_pdf_page_bytes(path, page_index=0)
      ├── OCR: PaddleOCR hoặc Ollama (theo setting hiện tại)
      ├── [nếu use_correction=True] text_corrector
      └── field_extractor.extract_fields(text, ollama_client)
      └── emit row_ready(dict) → append row vào table
  └── emit finished()
  ↓
OutputPanel tab "Kết quả Batch"
  → QTableWidget update real-time
  → Export CSV / Export Excel
```

---

## New Components

### 1. `extraction_pipeline.scan_first_page()`

```python
def scan_first_page(
    pdf_path: str,
    ollama_client,
    use_correction: bool = False,
    use_paddle: bool = True,
) -> dict:
    """
    OCR trang đầu (index 0) của 1 PDF, extract fields.
    Return: {
        "filename": str,
        "fields": {tac_gia, the_loai, ngay_thang_nam, trich_yeu, do_mat, nguoi_ky, loai_ban},
        "raw_text": str,
        "status": "ok" | "error",
        "error_msg": str | None,
    }
    """
```

- Dùng lại `file_handler.extract_pdf_page_bytes()` với `page_index=0`
- Dùng lại `field_extractor.extract_fields()`
- Wrap toàn bộ trong try/except, trả `status="error"` nếu fail (không crash batch)

### 2. `main_window.BatchScanWorker(QThread)`

```python
class BatchScanWorker(QThread):
    progress = Signal(int, int)   # (current_index, total)
    row_ready = Signal(dict)      # 1 kết quả scan
    finished = Signal()
    error = Signal(str)

    def __init__(self, pdf_paths: list[str], ollama_client, use_correction: bool):
        ...

    def run(self):
        for i, path in enumerate(self.pdf_paths):
            result = scan_first_page(path, self.ollama_client, self.use_correction)
            self.progress.emit(i + 1, len(self.pdf_paths))
            self.row_ready.emit(result)
        self.finished.emit()
```

- Có thể bị dừng giữa chừng qua flag `self._stop = True` (method `stop()`)

### 3. UI: `control_panel.py`

- Thêm button `QPushButton("Scan trang đầu")` dưới button "Bắt đầu xử lý"
- Click → mở `QFileDialog.getOpenFileNames(filter="PDF (*.pdf)")`
- Nếu có file → mở `ConfirmBatchDialog`

### 4. UI: `ConfirmBatchDialog` (nhỏ, inline trong `dialogs.py`)

- Hiển thị: "Đã chọn X file PDF"
- `QCheckBox("Dùng text correction (chậm hơn)")` — mặc định unchecked
- Button "Bắt đầu" / "Huỷ"

### 5. UI: Tab "Kết quả Batch" trong `output_panel.py`

**Layout:**
```
[Progress bar — ẩn khi không scan]
[QTableWidget]
  Columns: STT | Tên file | Tác giả | Thể loại | Ngày | Người ký | Độ mật | Trạng thái
[Xuất CSV]  [Xuất Excel]
```

- Rows append real-time khi `row_ready` signal tới
- Trạng thái: "✓ OK" (xanh) hoặc "✗ Lỗi" (đỏ)
- "Xuất CSV": dùng `csv` stdlib
- "Xuất Excel": dùng `openpyxl` (đã có trong deps hoặc thêm vào requirements)

---

## Error Handling

- File không phải PDF hoặc không đọc được → status="error", ghi vào cột Trạng thái, tiếp tục file tiếp theo
- Ollama/PaddleOCR fail → tương tự, không crash toàn batch
- Field extraction trả về rỗng → hiển thị "—" trong từng cell

---

## What Is NOT Changed

- `ocr_worker.py`, `text_corrector.py`, `image_viewer.py` — không đụng vào
- Workflow OCR đơn lẻ hiện tại — hoàn toàn giữ nguyên
- Config, theme, settings dialog — không thay đổi

---

## Dependencies

- `openpyxl` — export Excel (thêm vào `requirements.txt` nếu chưa có)
- Tất cả thành phần khác đã có sẵn

---

## Files To Modify / Create

| File | Thay đổi |
|------|----------|
| `src/extraction_pipeline.py` | Thêm `scan_first_page()` |
| `src/main_window.py` | Thêm `BatchScanWorker` class, wire signals |
| `src/ui/control_panel.py` | Thêm button "Scan trang đầu" |
| `src/ui/dialogs.py` | Thêm `ConfirmBatchDialog` |
| `src/ui/output_panel.py` | Thêm tab "Kết quả Batch" với table + export |
| `requirements.txt` | Thêm `openpyxl` nếu thiếu |
