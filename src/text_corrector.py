# src/text_corrector.py
# Post-OCR text correction using protonx-legal-tc (T5-based Vietnamese text correction model).
# Runs as a QThread after OCR completes to avoid blocking the UI.

import os
import re
from PySide6.QtCore import QThread, Signal

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "protonx-legal-tc")
MAX_TOKENS = 160  # Model's supported max context length


def _split_sentences(text):
    """Split text into sentences, preserving newlines as boundaries."""
    lines = text.split('\n')
    result = []
    for line in lines:
        if not line.strip():
            result.append(('newline', line))
            continue
        # Split on sentence-ending punctuation
        parts = re.split(r'(?<=[.!?])\s+', line.strip())
        for part in parts:
            if part:
                result.append(('text', part))
        result.append(('newline', ''))
    return result


class TextCorrectorWorker(QThread):
    """
    Worker thread that runs protonx-legal-tc on OCR output to fix:
    - Missing/incorrect Vietnamese diacritics
    - Broken word segmentation
    - Misrecognized legal terms
    - Punctuation artifacts
    """
    correction_done = Signal(str)   # Emits corrected full text when done
    error_occurred = Signal(str)    # Emits error message on failure
    progress = Signal(int, int)     # (current_sentence, total_sentences)

    def __init__(self, raw_text, model_path=None):
        super().__init__()
        self.raw_text = raw_text
        self.model_path = model_path or MODEL_DIR
        self.is_running = True

    def run(self):
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

            tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
            model = AutoModelForSeq2SeqLM.from_pretrained(self.model_path, local_files_only=True)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            model.eval()

            segments = _split_sentences(self.raw_text)
            text_segments = [(i, seg) for i, (kind, seg) in enumerate(segments) if kind == 'text']
            total = len(text_segments)

            corrected_map = {}
            for idx, (seg_i, sentence) in enumerate(text_segments):
                if not self.is_running:
                    break

                self.progress.emit(idx + 1, total)

                inputs = tokenizer(
                    sentence,
                    return_tensors="pt",
                    truncation=True,
                    max_length=MAX_TOKENS
                ).to(device)

                with torch.no_grad():
                    outputs = model.generate(
                        **inputs,
                        num_beams=4,
                        max_new_tokens=MAX_TOKENS,
                        early_stopping=True,
                    )

                corrected = tokenizer.decode(outputs[0], skip_special_tokens=True)
                corrected_map[seg_i] = corrected

            # Rebuild full text preserving structure
            result_parts = []
            for i, (kind, seg) in enumerate(segments):
                if kind == 'newline':
                    result_parts.append('\n')
                else:
                    result_parts.append(corrected_map.get(i, seg))

            self.correction_done.emit(''.join(result_parts))

        except ImportError:
            self.error_occurred.emit("missing_deps")
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self.is_running = False
