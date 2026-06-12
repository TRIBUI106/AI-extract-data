# src/extraction_pipeline.py
# Combines OCR image bytes → text_corrector → field_extractor → result dict.
# Designed to be imported by the PySide6 UI or run standalone for testing.

from __future__ import annotations

import sys
import os
from typing import Optional

from ollama import Client

# Allow running as a standalone script from the src/ directory
sys.path.insert(0, os.path.dirname(__file__))

from field_extractor import extract_fields, EXTRACTION_MODEL
import file_handler


def _ocr_image(img_bytes: bytes, client: Client, ocr_model: str, ocr_prompt: str) -> str:
    """
    Run the Ollama vision model on *img_bytes* and return the raw OCR text.
    Delegates to the same streaming approach used by ollama_service.py.
    """
    stream = client.chat(
        model=ocr_model,
        messages=[{
            "role": "user",
            "content": ocr_prompt,
            "images": [img_bytes],
        }],
        options={"temperature": 0},
        stream=True,
    )
    parts: list[str] = []
    for chunk in stream:
        content = chunk.get("message", {}).get("content", "")
        if content:
            parts.append(content)
    return "".join(parts)


def process_page(
    img_bytes: bytes,
    client: Client,
    ocr_model: str = "deepseek-ocr:3b",
    ocr_prompt: str = "<|grounding|>OCR this image.",
    extraction_model: str = EXTRACTION_MODEL,
    use_correction: bool = True,
) -> dict:
    """
    Full pipeline for a single page.

    Steps:
        1. OCR  : vision model converts image → raw Vietnamese text
        2. Correct (optional): protonx-legal-tc fixes OCR errors
        3. Extract: Ollama LLM extracts 6 structured fields

    Parameters
    ----------
    img_bytes        : Raw bytes of the page image (PNG, JPEG, etc.)
    client           : Initialised ollama.Client.
    ocr_model        : Ollama model tag for the OCR step.
    ocr_prompt       : Prompt sent to the vision model.
    extraction_model : Ollama model tag for field extraction.
    use_correction   : Whether to run text_corrector between OCR and extraction.
                       Set to False to skip the HuggingFace model download.

    Returns
    -------
    dict with keys: tac_gia, the_loai, ngay_thang_nam, trich_yeu,
                    do_mat, nguoi_ky, loai_ban, _raw_text, _corrected_text
    """
    raw_text = _ocr_image(img_bytes, client, ocr_model, ocr_prompt)

    if use_correction:
        from text_corrector import correct_text  # lazy import — triggers model load
        corrected_text = correct_text(raw_text)
    else:
        corrected_text = raw_text

    fields = extract_fields(corrected_text, client, model=extraction_model)

    # Attach intermediate text for debugging / UI display
    fields["_raw_text"] = raw_text
    fields["_corrected_text"] = corrected_text

    return fields


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
    filename = os.path.basename(pdf_path)
    empty_result = {
        "filename": filename,
        "fields": {},
        "raw_text": "",
        "status": "error",
        "error_msg": None,
    }

    try:
        img_bytes = file_handler.extract_pdf_page_bytes(pdf_path, page_index=0)
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

    text_for_extraction = raw_text
    if use_correction:
        try:
            from text_corrector import correct_text
            text_for_extraction = correct_text(raw_text)
        except Exception as exc:
            print(f"[scan_first_page] text_corrector skipped: {exc}")

    try:
        fields = extract_fields(text_for_extraction, client, model=EXTRACTION_MODEL)
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


def process_pdf(
    pdf_path: str,
    client: Client,
    pages: Optional[list[int]] = None,
    ocr_model: str = "deepseek-ocr:3b",
    ocr_prompt: str = "<|grounding|>OCR this image.",
    extraction_model: str = EXTRACTION_MODEL,
    use_correction: bool = True,
    dpi: int = 200,
) -> list[dict]:
    """
    Process all (or selected) pages of a PDF file.

    Parameters
    ----------
    pdf_path         : Absolute path to the PDF file.
    client           : Initialised ollama.Client.
    pages            : 1-based page numbers to process.  None = all pages.
    ocr_model        : Ollama vision model tag.
    ocr_prompt       : OCR prompt string.
    extraction_model : Ollama LLM tag for field extraction.
    use_correction   : Whether to run protonx-legal-tc text correction.
    dpi              : Rasterisation resolution (higher = better OCR, slower).

    Returns
    -------
    List of result dicts, one per processed page.
    Each dict includes a "page" key (1-based) plus the 7 extracted fields.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required for PDF processing: pip install pymupdf"
        ) from exc

    import io
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    page_indices: list[int]
    if pages is None:
        page_indices = list(range(total_pages))          # 0-based
    else:
        page_indices = [p - 1 for p in pages if 1 <= p <= total_pages]

    results: list[dict] = []
    for idx in page_indices:
        page = doc[idx]
        mat = fitz.Matrix(dpi / 72, dpi / 72)            # scale factor
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        result = process_page(
            img_bytes=img_bytes,
            client=client,
            ocr_model=ocr_model,
            ocr_prompt=ocr_prompt,
            extraction_model=extraction_model,
            use_correction=use_correction,
        )
        result["page"] = idx + 1
        results.append(result)
        print(f"[extraction_pipeline] Page {idx + 1}/{total_pages} done.")

    doc.close()
    return results
