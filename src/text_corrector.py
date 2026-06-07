# src/text_corrector.py
# Corrects Vietnamese OCR errors using protonx-models/protonx-legal-tc (ViT5-base Seq2Seq).
# Lazy-loads the model on first call and caches it as a module-level singleton.
#
# Install dependencies:
#   pip install transformers sentencepiece torch

from __future__ import annotations

import re
from typing import Optional

# Module-level singletons — populated on first call to correct_text()
_tokenizer = None
_model = None

_MODEL_ID = "protonx-models/protonx-legal-tc"
_MAX_INPUT_TOKENS = 150   # Max tokens per chunk sent to the model
_MAX_OUTPUT_TOKENS = 256  # Generator ceiling per chunk


def _load_model():
    """Download (if needed) and load the tokenizer + model into module globals."""
    global _tokenizer, _model

    if _tokenizer is not None and _model is not None:
        return  # Already loaded

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM  # type: ignore

    print(f"[text_corrector] Loading model '{_MODEL_ID}' (first-time download may take a while)…")
    _tokenizer = AutoTokenizer.from_pretrained(_MODEL_ID)
    _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_ID)
    _model.eval()
    print("[text_corrector] Model ready.")


def _split_into_chunks(text: str, max_tokens: int) -> list[str]:
    """
    Split *text* into sentence-boundary chunks where each chunk encodes to
    at most *max_tokens* tokens.  Falls back to word-level splitting when a
    single sentence exceeds the limit.
    """
    # Sentence splitter: split on '.', '!', '?', newlines (keep delimiter)
    sentence_re = re.compile(r'(?<=[.!?\n])\s*')
    sentences = sentence_re.split(text)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        encoded_len = len(_tokenizer.encode(sentence, add_special_tokens=False))

        # Single sentence too long — split by word
        if encoded_len > max_tokens:
            words = sentence.split()
            for word in words:
                word_len = len(_tokenizer.encode(word, add_special_tokens=False))
                if current_len + word_len > max_tokens and current_parts:
                    chunks.append(" ".join(current_parts))
                    current_parts = []
                    current_len = 0
                current_parts.append(word)
                current_len += word_len
            continue

        if current_len + encoded_len > max_tokens and current_parts:
            chunks.append(" ".join(current_parts))
            current_parts = []
            current_len = 0

        current_parts.append(sentence)
        current_len += encoded_len

    if current_parts:
        chunks.append(" ".join(current_parts))

    return chunks


def correct_text(text: str) -> str:
    """
    Fix Vietnamese OCR errors in *text* using the protonx-legal-tc model.

    The input is split into chunks of at most _MAX_INPUT_TOKENS tokens so the
    model never exceeds its context window.  Chunks are processed individually
    and the corrected pieces are joined with a single space.

    Returns the corrected text string.
    """
    if not text or not text.strip():
        return text

    _load_model()

    chunks = _split_into_chunks(text, _MAX_INPUT_TOKENS)
    corrected_chunks: list[str] = []

    for chunk in chunks:
        inputs = _tokenizer(
            chunk,
            return_tensors="pt",
            truncation=True,
            max_length=_MAX_INPUT_TOKENS,
        )
        outputs = _model.generate(
            **inputs,
            max_new_tokens=_MAX_OUTPUT_TOKENS,
            num_beams=4,
            early_stopping=True,
        )
        corrected = _tokenizer.decode(outputs[0], skip_special_tokens=True)
        corrected_chunks.append(corrected)

    return " ".join(corrected_chunks)
