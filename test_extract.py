"""
Quick CLI test script - scans a PDF and prints raw AI output.
Usage: python test_extract.py [pdf_path] [page_number]
Default: demo/demo2.pdf, page 1
"""

import sys
import os

# Add src/ to path (same as main.py)
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, src_dir)

import config
import file_handler
from ollama import Client
from ollama_service import stream_ocr_response

def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("demo", "A49.97.02-001-01-001-0001.pdf")
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1  # 1-based
    page_index = page_num - 1  # convert to 0-based

    if not os.path.exists(pdf_path):
        print(f"ERROR: File not found: {pdf_path}")
        sys.exit(1)

    page_count = file_handler.get_pdf_page_count(pdf_path)
    print(f"PDF: {pdf_path} ({page_count} pages)")
    print(f"Scanning page {page_num}/{page_count} ...")
    print(f"Model: {config.OLLAMA_MODEL}")
    print(f"Host:  {config.OLLAMA_HOST}")
    print("-" * 60)

    # Render the PDF page to image bytes
    img_bytes = file_handler.extract_pdf_page_bytes(pdf_path, page_index)
    print(f"Image size: {len(img_bytes):,} bytes")
    print("-" * 60)

    # Use the exact prompts from config.py (deepseek-ocr requires specific format)
    prompt = config.PROMPTS["p_ocr"]  # "<|grounding|>OCR this image."

    print("AI OUTPUT:")
    print("-" * 60)

    client = Client(host=config.OLLAMA_HOST)

    full_text = []
    for chunk in stream_ocr_response(client, config.OLLAMA_MODEL, prompt, img_bytes, config.INFERENCE_PARAMS):
        print(chunk, end="", flush=True)
        full_text.append(chunk)

    print()
    print("-" * 60)
    print(f"Total characters: {len(''.join(full_text))}")

if __name__ == "__main__":
    main()
