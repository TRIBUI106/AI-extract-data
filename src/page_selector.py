# src/page_selector.py
# Selects relevant pages from a PDF for OCR:
#   - Always includes page 0 (header/metadata)
#   - Detects "closing pages" containing seals (red/blue circles) or
#     signature keywords — these mark the end of a document or attachment
#
# Strategy: fast pixel-level analysis on each page rendered at low DPI,
# so no extra model is needed. Takes ~0.05s per page at 72 DPI.

import re
import numpy as np

# Vietnamese government document closing keywords
_SIGNATURE_KEYWORDS = re.compile(
    r'\b(k[íi]nh\s+g[uư][iử]i|k[íi]nh\s+tr[iì]nh'
    r'|[Tt][Mm]\.|[Kk][Tt]\.|[Pp][Pp]\.'
    r'|[Cc][Hh][Uu][Yy][Ee][Nn]\s+[Vv][Ii][Ee][Nn]'
    r'|[Tt][Hh][Uu][Aa][Yy]\s+[Mm][Aa][Tt]'
    r'|[Cc][Hh][Uu][Cc]\s+[Vv][Uu]|[Cc][Hh][Uu][CC][Cc]\s+[Vv][Ụụ]'
    r'|k[yý]\s+t[eê]n|k[yý]\s+v[àa]\s+[dđ][oó]ng\s+d[aấ]u'
    r'|[Nn][Oo][Ii]\s+[Nn][Hh][Aa][Nn]|[Nn][Ơơ][Ii]\s+[Nn][Hh][Ậậ][Nn]'
    r'|[Tt][Rr][Ưư][Ởở][Nn][Gg]\s+[Pp][Hh][Òò][Nn][Gg]'
    r'|[Gg][Ii][Áá][Mm]\s+[Đđ][Ốố][Cc]'
    r'|\.\s*\.\s*\.\s*\/\s*\.\s*\.\s*\.'  # date pattern .../../..
    r')',
    re.UNICODE | re.IGNORECASE,
)


def _render_page_np(pdf_path: str, page_index: int, dpi: int = 72) -> np.ndarray:
    """Render a PDF page to a uint8 RGB numpy array at given DPI."""
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    doc.close()
    return arr.copy()


def _has_red_seal(img_rgb: np.ndarray) -> bool:
    """
    Detect a red circular seal (dấu mộc đỏ).
    Uses HSV colour thresholding + Hough circle detection.
    """
    import cv2
    img_hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)

    # Red hue wraps around 0/180 in HSV
    mask1 = cv2.inRange(img_hsv, (0, 60, 60), (10, 255, 255))
    mask2 = cv2.inRange(img_hsv, (165, 60, 60), (180, 255, 255))
    red_mask = cv2.bitwise_or(mask1, mask2)

    # Need a meaningful red area (>0.3% of page)
    red_ratio = red_mask.sum() / (red_mask.size * 255)
    if red_ratio < 0.003:
        return False

    # Try to find circles in the red channel
    gray = cv2.bitwise_and(
        cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY),
        cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY),
        mask=red_mask,
    )
    gray = cv2.GaussianBlur(gray, (9, 9), 2)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=30,
        param1=50,
        param2=20,
        minRadius=15,
        maxRadius=min(img_rgb.shape[:2]) // 3,
    )
    return circles is not None


def _has_blue_seal(img_rgb: np.ndarray) -> bool:
    """Detect a blue circular seal (dấu mộc xanh)."""
    import cv2
    img_hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    blue_mask = cv2.inRange(img_hsv, (100, 60, 60), (140, 255, 255))
    blue_ratio = blue_mask.sum() / (blue_mask.size * 255)
    if blue_ratio < 0.003:
        return False
    gray = cv2.bitwise_and(
        cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY),
        cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY),
        mask=blue_mask,
    )
    gray = cv2.GaussianBlur(gray, (9, 9), 2)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=30,
        param1=50, param2=20, minRadius=15,
        maxRadius=min(img_rgb.shape[:2]) // 3,
    )
    return circles is not None


def _has_signature_keyword(pdf_path: str, page_index: int) -> bool:
    """
    Extract text from the PDF page natively (no OCR) and check for
    signature/closing keywords. Fast and reliable for text-layer PDFs.
    Falls back gracefully if the page has no text layer.
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = doc[page_index].get_text("text")
        doc.close()
        return bool(_SIGNATURE_KEYWORDS.search(text))
    except Exception:
        return False


def is_closing_page(pdf_path: str, page_index: int) -> bool:
    """
    Return True if the page looks like a document closing page
    (contains a seal or signature keywords).
    """
    try:
        img = _render_page_np(pdf_path, page_index, dpi=72)
        if _has_red_seal(img) or _has_blue_seal(img):
            return True
    except Exception:
        pass

    return _has_signature_keyword(pdf_path, page_index)


def select_pages(pdf_path: str, total_pages: int) -> list[int]:
    """
    Return sorted list of 0-based page indices to OCR.

    Rules:
    - Always include page 0
    - Include any page that looks like a document closing page
      (seal or signature keywords)
    - At minimum return [0] even if no closing page found
    """
    selected = {0}

    for i in range(1, total_pages):
        if is_closing_page(pdf_path, i):
            selected.add(i)

    return sorted(selected)
