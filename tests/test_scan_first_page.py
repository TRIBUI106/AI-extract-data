import pytest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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
        result = scan_first_page("/fake/path/doc.pdf", mock_client, use_correction=False, use_paddle=False)

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
        result = scan_first_page("/fake/nonexistent.pdf", mock_client, use_paddle=False)

    assert result["status"] == "error"
    assert result["filename"] == "nonexistent.pdf"
    assert "File not found" in result["error_msg"]
    assert result["fields"] == {}


def test_ocr_image_bytes_callback_called_per_block(monkeypatch):
    """callback is called once per non-empty block in parsing_res_list fallback path."""
    import paddle_ocr_service

    fake_result = MagicMock()
    fake_result.markdown = None  # force fallback path
    type(fake_result).markdown = property(lambda self: (_ for _ in ()).throw(Exception("no md")))
    fake_result.json = {
        "parsing_res_list": [
            {"block_order": 0, "block_content": "Block one"},
            {"block_order": 1, "block_content": ""},
            {"block_order": 2, "block_content": "Block two"},
        ]
    }

    fake_pipeline = MagicMock()
    fake_pipeline.predict.return_value = [fake_result]
    monkeypatch.setattr(paddle_ocr_service, "_pipeline_instance", fake_pipeline)

    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(b"\x89PNG" + b"\x00" * 10)
    tmp.close()

    collected = []
    try:
        result = paddle_ocr_service.ocr_image_bytes(b"\x89PNG" + b"\x00" * 10, callback=collected.append)
    finally:
        os.unlink(tmp.name)

    assert "Block one\n" in collected
    assert "Block two\n" in collected
    # empty block must be skipped
    assert len(collected) == 2
    assert "Block one" in result
    assert "Block two" in result
