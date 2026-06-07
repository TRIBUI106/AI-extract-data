# src/field_extractor.py
# Extracts structured fields from Vietnamese legal document text using Ollama.
# Uses client.chat() so that reasoning-model output (qwen3, deepseek-r1, etc.)
# is always available in message.content for JSON extraction.

from __future__ import annotations

import json
import re
from typing import Optional

from ollama import Client

EXTRACTION_MODEL = "qwen3:4b"

# Fields returned when extraction fails entirely
_EMPTY_RESULT: dict = {
    "tac_gia": "",
    "the_loai": "",
    "ngay_thang_nam": "",
    "trich_yeu": "",
    "do_mat": "",
    "nguoi_ky": "",
    "loai_ban": "unknown",
}

_PROMPT_TEMPLATE = """\
Đọc văn bản hành chính Việt Nam sau và trích xuất các trường dữ liệu.
Chỉ trả về JSON hợp lệ, không giải thích thêm, không markdown, không dấu ```json.

Văn bản:
{text}

Trả về JSON với đúng các trường sau (để trống "" nếu không tìm thấy):
{{
  "tac_gia": "tên cơ quan hoặc tác giả ban hành văn bản",
  "the_loai": "thể loại văn bản (Công văn, Quyết định, Thông báo, v.v.)",
  "ngay_thang_nam": "ngày tháng năm theo định dạng DD/MM/YYYY",
  "trich_yeu": "trích yếu nội dung văn bản",
  "do_mat": "độ mật (Tuyệt mật / Tối mật / Mật) hoặc để trống nếu không có",
  "nguoi_ky": "họ tên người ký văn bản",
  "loai_ban": "unknown"
}}
"""


def _build_prompt(text: str) -> str:
    return _PROMPT_TEMPLATE.format(text=text)


def _parse_json_response(raw: str) -> dict:
    """
    Extract the JSON object from the model response.

    qwen3 (and other reasoning models) may prepend a long chain-of-thought
    before the actual JSON output.  Strategy:
      1. Strip markdown code fences.
      2. Find ALL {...} blocks and try them from last to first — the final
         block is almost always the structured answer, not reasoning text.
      3. Validate that the parsed object contains at least one expected key.
    Returns _EMPTY_RESULT on any parse failure.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    # Also strip <think>...</think> blocks used by some models
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    # Collect all {...} spans
    matches = list(re.finditer(r"\{[^{}]*\}", cleaned, re.DOTALL))
    # Also try greedy multi-level match for nested-looking objects
    matches += list(re.finditer(r"\{.*\}", cleaned, re.DOTALL))

    # Deduplicate by start position, prefer longer matches
    seen: dict[int, re.Match] = {}
    for m in matches:
        start = m.start()
        if start not in seen or len(m.group()) > len(seen[start].group()):
            seen[start] = m

    # Try from last occurrence to first (reasoning models output JSON at end)
    candidates = sorted(seen.values(), key=lambda m: m.start(), reverse=True)

    expected_keys = {"tac_gia", "the_loai", "ngay_thang_nam", "trich_yeu",
                     "do_mat", "nguoi_ky", "loai_ban"}
    data = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.group())
            if isinstance(parsed, dict) and expected_keys & parsed.keys():
                data = parsed
                break
        except json.JSONDecodeError:
            continue

    if data is None:
        return dict(_EMPTY_RESULT)

    # Normalise: ensure all expected keys exist, force loai_ban to "unknown"
    result = dict(_EMPTY_RESULT)
    for key in result:
        if key == "loai_ban":
            result["loai_ban"] = "unknown"
        elif key in data:
            result[key] = str(data[key]).strip()

    return result


def extract_fields(
    text: str,
    client: Client,
    model: str = EXTRACTION_MODEL,
) -> dict:
    """
    Extract 6 structured fields from Vietnamese legal document *text*.

    Parameters
    ----------
    text   : Raw (or corrected) OCR text of the document page.
    client : An initialised ollama.Client instance.
    model  : Ollama model tag to use (default: qwen3:4b).

    Returns
    -------
    dict with keys:
        tac_gia, the_loai, ngay_thang_nam, trich_yeu,
        do_mat, nguoi_ky, loai_ban
    loai_ban is always "unknown" — it requires image colour analysis.
    """
    if not text or not text.strip():
        return dict(_EMPTY_RESULT)

    prompt = _build_prompt(text)

    try:
        # Use chat() rather than generate():
        # With reasoning models (qwen3, deepseek-r1, etc.) generate() places
        # chain-of-thought in response.thinking and leaves response.response
        # empty when the thinking budget is exhausted.  chat() always puts the
        # full output (including any <think>…</think> markup) in
        # message.content, which our parser can strip.
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
        raw_text: str = (
            response.message.content
            if hasattr(response, "message") and hasattr(response.message, "content")
            else str(response)
        )
    except Exception as exc:
        print(f"[field_extractor] Ollama chat() failed: {exc}")
        return dict(_EMPTY_RESULT)

    return _parse_json_response(raw_text)
