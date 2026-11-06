"""Load any supported input into a list of page images (and text when it is exact).

Supported: scanned PDF, vector PDF (text layer used when present), JPG/PNG, Word .docx.
Every page becomes a PIL image so findings can always be shown as screenshots.
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

from PIL import Image

Image.MAX_IMAGE_PIXELS = 400_000_000

TARGET_DPI = 300          # render vector pages at this resolution
MIN_SCAN_DPI = 180        # below this, scans are upscaled before OCR


@dataclass
class Page:
    index: int
    image: Image.Image                     # RGB, used for OCR and screenshots
    words: list | None = None              # exact words from a PDF text layer / docx, if any
    source_dpi: float = 72.0


@dataclass
class Document:
    name: str
    kind: str                              # "pdf-scan", "pdf-vector", "image", "docx"
    pages: list[Page] = field(default_factory=list)
    plain_text: str | None = None          # docx only: approved text without layout


def _pdf_pages(path: str) -> Document:
    import pypdfium2 as pdfium
    import pdfplumber

    doc = Document(name=os.path.basename(path), kind="pdf-scan")
    pdf = pdfium.PdfDocument(path)
    with pdfplumber.open(path) as plumb:
        for i, page in enumerate(pdf):
            w_pt, h_pt = page.get_size()
            pl_page = plumb.pages[i]
            chars = pl_page.chars
            # Pick a render scale: native resolution of the largest embedded image,
            # or TARGET_DPI for vector content.
            native_scale = None
            for im in pl_page.images:
                iw, ih = im.get("srcsize", (0, 0))
                bw = im["x1"] - im["x0"]
                if bw > 0.5 * w_pt and iw:
                    native_scale = max(native_scale or 0, iw / bw)
            if chars:
                scale = TARGET_DPI / 72
                doc.kind = "pdf-vector"
            elif native_scale:
                scale = native_scale
            else:
                scale = TARGET_DPI / 72
            # Guard against huge raster sizes
            max_side = 9000
            scale = min(scale, max_side / max(w_pt, h_pt))
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil().convert("RGB")
            words = None
            if chars:
                words = []
                for w in pl_page.extract_words(keep_blank_chars=False, use_text_flow=True):
                    words.append({
                        "text": w["text"],
                        "box": [w["x0"] * scale, w["top"] * scale, w["x1"] * scale, w["bottom"] * scale],
                        "conf": 100.0,
                    })
            doc.pages.append(Page(index=i, image=img, words=words, source_dpi=72 * scale))
    return doc


def _image_page(path: str) -> Document:
    img = Image.open(path)
    dpi = img.info.get("dpi", (200, 200))[0] or 200
    return Document(name=os.path.basename(path), kind="image",
                    pages=[Page(index=0, image=img.convert("RGB"), source_dpi=float(dpi))])


def _docx(path: str) -> Document:
    """Approved text from Word. Rendered to images via LibreOffice when available,
    so findings can still be shown as screenshots; otherwise text-only."""
    import docx

    d = docx.Document(path)
    paras = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                if cell.text.strip():
                    paras.append(cell.text)
    doc = Document(name=os.path.basename(path), kind="docx", plain_text="\n".join(paras))
    soffice = _which("soffice") or _which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, path],
                           check=False, capture_output=True, timeout=180)
            pdfs = [f for f in os.listdir(tmp) if f.endswith(".pdf")]
            if pdfs:
                rendered = _pdf_pages(os.path.join(tmp, pdfs[0]))
                doc.pages = rendered.pages
    return doc


def _which(cmd: str) -> str | None:
    from shutil import which
    return which(cmd)


def load(path: str) -> Document:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _pdf_pages(path)
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        return _image_page(path)
    if ext == ".docx":
        return _docx(path)
    raise ValueError(f"Unsupported file type: {ext}")
