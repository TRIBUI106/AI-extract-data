# src/paddle_ocr_service.py
# Wraps PaddleOCR v5 (paddleocr 3.6.x / paddlepaddle 3.x) for use in the app.
#
# Key design decisions:
# - Singleton OCR instance: model weights are loaded once at first call, then
#   reused for every subsequent image. Avoids multi-second re-init per page.
# - Input: raw PNG/JPEG bytes as produced by file_handler.py
# - Output: plain UTF-8 text with lines joined by newlines

import io
import os
import numpy as np
from PIL import Image
import config

# Disable OneDNN (MKL-DNN) — causes ConvertPirAttribute crash on paddlepaddle 3.x
os.environ.setdefault("FLAGS_use_mkldnn", "0")

_ocr_instance = None


def _get_ocr():
    """Return (and lazily initialise) the singleton PaddleOCR instance."""
    global _ocr_instance
    if _ocr_instance is None:
        from paddleocr import PaddleOCR  # deferred import keeps app startup fast
        _ocr_instance = PaddleOCR(
            lang=config.PADDLE_OCR_LANG,
            use_textline_orientation=True,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )
    return _ocr_instance


def _img_bytes_to_numpy(img_bytes: bytes) -> np.ndarray:
    """Convert raw image bytes to a uint8 RGB numpy array."""
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)


def _extract_text(predict_results: list) -> str:
    """
    Extract plain text from the list returned by PaddleOCR.predict().

    Each element of predict_results is an OCRResult dict-like object.
    The recognised lines are stored in result['rec_texts'] as a list of str.
    Lines are joined with newlines; multiple result pages (rare for a single
    image) are separated by a blank line.
    """
    page_texts = []
    for result in predict_results:
        texts = result.get("rec_texts", [])
        page_texts.append("\n".join(t for t in texts if t))
    return "\n\n".join(block for block in page_texts if block)


def ocr_image_bytes(img_bytes: bytes) -> str:
    """
    Run PaddleOCR on raw image bytes and return all recognised text.

    Args:
        img_bytes: PNG/JPEG bytes from file_handler.py

    Returns:
        Plain text string with newline-separated lines.
        Returns empty string if nothing is recognised or on error.
    """
    try:
        ocr = _get_ocr()
        img_array = _img_bytes_to_numpy(img_bytes)
        results = ocr.predict(img_array)
        return _extract_text(results)
    except Exception as e:
        print(f"[paddle_ocr_service] ocr_image_bytes error: {e}")
        return ""


def ocr_image_bytes_stream(img_bytes: bytes):
    """
    Run PaddleOCR and yield text line-by-line for streaming UI updates.

    PaddleOCR v5 does not support true token streaming, so this function
    runs the full inference once then yields each recognised line as a
    separate chunk, mimicking streaming behaviour.

    Yields:
        str: One recognised text line at a time (with trailing newline).
             Yields an empty string and returns immediately on error.
    """
    try:
        ocr = _get_ocr()
        img_array = _img_bytes_to_numpy(img_bytes)
        results = ocr.predict(img_array)
        for result in results:
            texts = result.get("rec_texts", [])
            for line in texts:
                if line:
                    yield line + "\n"
    except Exception as e:
        print(f"[paddle_ocr_service] ocr_image_bytes_stream error: {e}")
        yield ""
