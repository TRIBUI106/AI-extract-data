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
