"""Synthetic Braille, dieline and graphics test material."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

LETTERS = {"a": (1,), "b": (1, 2), "c": (1, 4), "d": (1, 4, 5), "e": (1, 5), "f": (1, 2, 4), "g": (1, 2, 4, 5),
           "h": (1, 2, 5), "i": (2, 4), "j": (2, 4, 5), "k": (1, 3), "l": (1, 2, 3), "m": (1, 3, 4), "n": (1, 3, 4, 5),
           "o": (1, 3, 5), "p": (1, 2, 3, 4), "r": (1, 2, 3, 5), "s": (2, 3, 4), "t": (2, 3, 4, 5), "u": (1, 3, 6),
           "#": (3, 4, 5, 6), ".": (2, 5, 6)}


def braille_image(text: str, dpi: int = 300, embossed: bool = False) -> Image.Image:
    px = dpi / 25.4
    im = Image.new("RGB", (int(150 * px), int(40 * px)), (250, 250, 248))
    d = ImageDraw.Draw(im)
    x, y = 10 * px, 12 * px
    digits = {"1": "a", "2": "b", "3": "c", "4": "d", "5": "e", "6": "f", "7": "g", "8": "h", "9": "i", "0": "j"}
    seq, num = [], False
    for ch in text:
        if ch.isdigit():
            if not num:
                seq.append("#")
                num = True
            seq.append(digits[ch])
        else:
            if ch == " ":
                num = False
            seq.append(ch)
    r = 0.75 * px
    for ch in seq:
        if ch == " ":
            x += 6.2 * px
            continue
        for dot in LETTERS[ch]:
            col = 0 if dot <= 3 else 1
            row = (dot - 1) % 3
            cx, cy = x + col * 2.5 * px, y + row * 2.5 * px
            fill = (205, 205, 200) if embossed else (40, 40, 40)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        x += 6.2 * px
    return im


def dieline_pdf() -> bytes:
    from reportlab.lib.colors import CMYKColor
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(200 * mm, 120 * mm))
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 60 * mm, "Nerkardou 2.5 mg oral dissolvable film - 30 films")   # crosses fold at x=60mm
    c.drawString(150 * mm, 30 * mm, "Store below 30 C")
    c.drawString(10.6 * mm, 100 * mm, "Edge text")                                          # 0.6 mm from cut
    die = CMYKColor(0, 1, 0, 0, spotName="Dieline", density=1)
    c.setStrokeColor(die)
    c.setLineWidth(0.5)
    c.rect(10 * mm, 10 * mm, 180 * mm, 100 * mm, stroke=1, fill=0)
    c.setDash(3, 2)
    c.line(60 * mm, 10 * mm, 60 * mm, 110 * mm)
    c.line(130 * mm, 10 * mm, 130 * mm, 110 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()
