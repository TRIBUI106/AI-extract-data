# src/paddle_ocr_service.py
# Wraps PaddleOCR-VL v1.5 (paddleocr[doc-parser]) for document/PDF OCR.
#
# Key design decisions:
# - Singleton pipeline: model weights loaded once, reused for every page.
# - Input: raw PNG/JPEG bytes from file_handler.py, written to a temp file
#   because PaddleOCRVL.predict() accepts a file path, not raw bytes.
# - Output: plain UTF-8 markdown text (VL outputs richer structure than
#   the classic rec_texts list).

import io
import os
import tempfile

import config

_pipeline_instance = None


def _get_pipeline():
    """Return (and lazily initialise) the singleton PaddleOCRVL pipeline."""
    global _pipeline_instance
    if _pipeline_instance is None:
        from paddleocr import PaddleOCRVL  # deferred import keeps startup fast
        import paddle
        device = "gpu" if paddle.device.cuda.device_count() > 0 else "cpu"
        print(f"[paddle_ocr_service] Using device: {device}")
        _pipeline_instance = PaddleOCRVL(
            pipeline_version="v1.5",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            device=device,
        )
    return _pipeline_instance


def _extract_markdown(result) -> str:
    """
    Extract plain text from a PaddleOCRVL result object.

    VL-1.5 returns a result with a .markdown property:
      { 'markdown_texts': str, 'markdown_images': ..., 'page_continuation_flags': ... }

    Falls back to iterating parsing_res_list if markdown is unavailable.
    """
    # Primary path: markdown output
    try:
        md = result.markdown
        if isinstance(md, dict):
            text = md.get("markdown_texts", "")
        else:
            text = str(md)
        if text and text.strip():
            return text.strip()
    except Exception:
        pass

    # Fallback: parse the JSON result structure
    try:
        data = result.json
        blocks = data.get("parsing_res_list", [])
        lines = []
        for block in sorted(blocks, key=lambda b: b.get("block_order", 0)):
            content = block.get("block_content", "")
            if content and content.strip():
                lines.append(content.strip())
        return "\n".join(lines)
    except Exception:
        pass

    return ""


def ocr_image_bytes(img_bytes: bytes) -> str:
    """
    Run PaddleOCR-VL v1.5 on raw image bytes and return recognised text.

    PaddleOCRVL.predict() expects a file path, so the bytes are written to
    a temporary file, processed, then cleaned up.

    Args:
        img_bytes: PNG/JPEG bytes from file_handler.py

    Returns:
        Plain text / markdown string.  Empty string on error.
    """
    tmp_path = None
    try:
        # Detect format from magic bytes
        suffix = ".jpg"
        if img_bytes[:4] == b"\x89PNG":
            suffix = ".png"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        pipeline = _get_pipeline()
        results = list(pipeline.predict(tmp_path))

        page_texts = []
        for res in results:
            text = _extract_markdown(res)
            if text:
                page_texts.append(text)

        return "\n\n".join(page_texts)

    except Exception as e:
        print(f"[paddle_ocr_service] ocr_image_bytes error: {e}")
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
