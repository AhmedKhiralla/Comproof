"""Barcode test artwork drawn with ReportLab into a PDF (EAN-13, Code 128, QR, DataMatrix)."""
from __future__ import annotations

import io

from PIL import Image


def pdf(codes: list[tuple[str, str]]) -> bytes:
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.lib.pagesizes import A5, landscape
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A5))
    c.setFont("Helvetica", 9)
    c.drawString(30, 380, "Nerkardou 2.5 mg oral dissolvable film - barcode panel")
    x = 30
    for kind, value in codes:
        if kind == "EAN13":
            d = createBarcodeDrawing("EAN13", value=value, barHeight=50, barWidth=1.0)
        elif kind == "Code128":
            d = createBarcodeDrawing("Code128", value=value, barHeight=45, barWidth=0.9, humanReadable=False)
        elif kind == "QR":
            d = createBarcodeDrawing("QR", value=value, width=110, height=110)
        else:
            d = createBarcodeDrawing("ECC200DataMatrix", value=value, width=90, height=90)
        renderPDF.draw(d, c, x, 200)
        x += d.width + 30
    c.showPage()
    c.save()
    return buf.getvalue()


def render(pdf_data: bytes, dpi: int = 300) -> Image.Image:
    import pypdfium2 as pdfium
    p = pdfium.PdfDocument(pdf_data)[0]
    return p.render(scale=dpi / 72).to_pil().convert("RGB")
