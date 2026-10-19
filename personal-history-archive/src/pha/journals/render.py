"""PDF page rendering and perceptual hashing for duplicate-scan detection."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def page_count(pdf: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return len(doc)
    finally:
        doc.close()


def render_page(pdf: Path, page_number: int, out_png: Path, dpi: int) -> Path:
    """Render a 1-based page to PNG in the cache (the PDF is only read)."""
    if out_png.exists():
        return out_png
    import pypdfium2 as pdfium

    out_png.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    try:
        page = doc[page_number - 1]
        image = page.render(scale=dpi / 72).to_pil()
        tmp = out_png.with_suffix(".partial.png")
        image.save(tmp, format="PNG")
        tmp.replace(out_png)
    finally:
        doc.close()
    return out_png


def dhash(image_path: Path, size: int = 8) -> str:
    """64-bit difference hash; robust to re-scans at different resolutions."""
    with Image.open(image_path) as im:
        small = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = np.asarray(small, dtype=np.int16)
    bits = (px[:, 1:] > px[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def ink_ratio(image_path: Path) -> float:
    """Share of dark pixels; near zero for blank pages (which all hash alike)."""
    with Image.open(image_path) as im:
        small = np.asarray(im.convert("L").resize((200, 260)), dtype=np.uint8)
    return float((small < 128).mean())
