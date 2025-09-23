"""
PyPDF2 Text Extraction
"""
from typing import List

def extract_pdf_text(file_content: bytes) -> str:
    from PyPDF2 import PdfReader
    import io
    pdf_stream = io.BytesIO(file_content)
    reader = PdfReader(pdf_stream)
    parts: List[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    full_text = "\n\n".join(parts).strip()
    if not full_text:
        raise RuntimeError("No extractable text found in PDF (it might be scanned images)")
    return full_text
