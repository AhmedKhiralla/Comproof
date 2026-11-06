"""Synthetic shade cards: one artwork printed Standard, Light (less ink) and Dark (more ink), 'scanned'
with a small rotation, scale change, noise and a colour cast."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

INKS = {"red": (200, 30, 45), "blue": (25, 70, 160), "green": (40, 140, 70), "yellow": (240, 200, 30)}


def artwork(strength: float = 1.0, w: int = 1800, h: int = 1200, shift: dict | None = None) -> Image.Image:
    """strength < 1 = lighter print (ink mixed with paper), > 1 = heavier (ink darkened)."""
    rng = np.random.default_rng(7)
    im = Image.new("RGB", (w, h), (250, 249, 245))
    d = ImageDraw.Draw(im)

    def ink(c):
        c = np.array(c, float)
        if shift and tuple(c.astype(int)) in [tuple(np.array(v)) for v in shift]:
            c = c + np.array(shift[tuple(c.astype(int))])
        if strength < 1:
            c = c * strength + np.array([250, 249, 245]) * (1 - strength)
        else:
            c = c / strength
        return tuple(int(x) for x in np.clip(c, 0, 255))

    d.rectangle([60, 60, 760, 330], fill=ink(INKS["red"]))
    d.rectangle([60, 380, 760, 560], fill=ink(INKS["blue"]))
    d.rectangle([860, 60, 1700, 260], fill=ink(INKS["green"]))
    d.ellipse([900, 330, 1250, 680], fill=ink(INKS["yellow"]))
    font = ImageFont.load_default()
    for i in range(40):                      # texture for alignment: black "text" and marks
        x, y = int(rng.integers(60, w - 300)), int(rng.integers(620, h - 40))
        d.text((x, y), f"Nerkardou {i} mg LOT{i * 7}", fill=(20, 20, 20), font=font)
        d.rectangle([x, y + 14, x + int(rng.integers(20, 120)), y + 16], fill=(20, 20, 20))
    for i in range(25):
        x, y = int(rng.integers(1300, w - 60)), int(rng.integers(320, 700))
        d.line([x, y, x + 40, y + int(rng.integers(-30, 30))], fill=(20, 20, 20), width=3)
    return im


def scan(im: Image.Image, angle: float = 0.6, scale: float = 0.97, cast=(1.0, 0.97, 0.93), noise: float = 2.0) -> bytes:
    w, h = im.size
    out = im.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    out = out.resize((int(w * scale), int(h * scale)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(out, float) * np.array(cast)
    a += np.random.default_rng(3).normal(0, noise, a.shape)
    buf = io.BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(buf, "PNG", dpi=(300, 300))
    return buf.getvalue()


def with_chart(im: Image.Image, x: int = 1320, y: int = 760, patch: int = 60) -> Image.Image:
    """Paste a ColorChecker Classic (4 x 6) into the artwork."""
    from app.engine.colour import COLORCHECKER_SRGB
    im = im.copy()
    d = ImageDraw.Draw(im)
    d.rectangle([x - 12, y - 12, x + 6 * (patch + 10) + 2, y + 4 * (patch + 10) + 2], fill=(25, 25, 25))
    for i, c in enumerate(COLORCHECKER_SRGB):
        r, k = divmod(i, 6)
        x0, y0 = x + k * (patch + 10), y + r * (patch + 10)
        d.rectangle([x0, y0, x0 + patch, y0 + patch], fill=tuple(int(v) for v in c))
    return im
