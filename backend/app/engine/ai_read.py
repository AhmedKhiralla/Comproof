"""AI reading of scanned text: the vision model transcribes each tile, OCR keeps the positions.

OCR (Tesseract) is good at *where* text is and poor at *what* dense Arabic or small print says.
A vision model is the reverse. Each region is cut into tiles at blank rows; the model transcribes
each tile; its lines are aligned to the OCR lines of that tile, and every OCR line takes the AI text
while keeping its own box. Words get boxes in proportion to their length inside the line box, so
highlights stay close to the right place. Lines the OCR missed entirely are inserted between their
neighbours. If the AI call fails, the OCR text is kept and the failure is reported.
"""
from __future__ import annotations

import logging
import threading
from difflib import SequenceMatcher

from PIL import Image, ImageOps

from . import ai
from .layout import Line, Region, Word, _bands

log = logging.getLogger("comproof.ai")
TILE_TARGET_H = 700            # page pixels per tile; small enough for the model to read 6-7 pt print
MAX_TILE_W = 1600


def _norm(s: str) -> str:
    from .compare import norm_word
    lang = "ara" if any("؀" <= c <= "ۿ" for c in s) else "eng"
    return "".join(t for w in s.split() for t in norm_word(w, lang))


def _align(ocr: list[str], ai_lines: list[str]) -> list[tuple[int | None, int | None]]:
    """Monotonic alignment (Needleman-Wunsch, similarity score, free gaps)."""
    n, m = len(ocr), len(ai_lines)
    a = [_norm(x) for x in ocr]
    b = [_norm(x) for x in ai_lines]
    sim = [[SequenceMatcher(None, a[i], b[j], autojunk=False).ratio() if a[i] and b[j] else 0.0 for j in range(m)]
           for i in range(n)]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        back[i][0] = 1
    for j in range(1, m + 1):
        back[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim[i - 1][j - 1]
            opts = [(score[i - 1][j - 1] + (s if s >= 0.35 else -1.0), 0), (score[i - 1][j], 1), (score[i][j - 1], 2)]
            score[i][j], back[i][j] = max(opts)
    out = []
    i, j = n, m
    while i > 0 or j > 0:
        k = back[i][j]
        if i > 0 and j > 0 and k == 0:
            out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and (k == 1 or j == 0):
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return out[::-1]


def _words_in_box(text: str, box: list, rtl: bool, conf: float = 96.0) -> list[Word]:
    words = text.split()
    if not words:
        return []
    x0, y0, x1, y1 = box
    total = sum(len(w) for w in words) + (len(words) - 1)
    unit = (x1 - x0) / max(1, total)
    out, pos = [], 0.0
    for w in words:
        a, b = pos * unit, (pos + len(w)) * unit
        bx = [x1 - b, y0, x1 - a, y1] if rtl else [x0 + a, y0, x0 + b, y1]
        out.append(Word(w, bx, conf))
        pos += len(w) + 1
    return out


def make_reader(provider: ai.Provider, stats: dict, lock: threading.Lock):
    """Returns reader(gray, region, rotate) for layout.analyse_page."""

    def reader(gray: Image.Image, reg: Region, rotate: int) -> Region:
        if rotate:                      # rotated panels: keep OCR (positions are mapped from a rotated image)
            return reg
        rtl = reg.lang == "ara"
        new_lines: list[Line] = []
        for band in _bands(gray, reg.box, target=TILE_TARGET_H):
            bx0, by0, bx1, by1 = band
            in_band = [ln for ln in reg.lines if by0 <= (ln.box[1] + ln.box[3]) / 2 < by1]
            tile = ImageOps.autocontrast(gray.crop((bx0, by0, bx1, by1)))
            if tile.width > MAX_TILE_W:
                tile = tile.resize((MAX_TILE_W, int(tile.height * MAX_TILE_W / tile.width)), Image.LANCZOS)
            elif tile.width < 700:
                f = 700 / tile.width
                tile = tile.resize((700, int(tile.height * f)), Image.LANCZOS)
            if stats.get("config_error"):
                new_lines += in_band            # provider refused the request: keep OCR, stop calling it
                continue
            try:
                model, lines = ai.read_tile(provider, tile, reg.lang)
                with lock:
                    stats["tiles"] = stats.get("tiles", 0) + 1
                    stats["model"] = model
            except ai.AIUnavailable as e:
                with lock:
                    if isinstance(e, ai.AIConfigError):
                        stats["config_error"] = True
                    stats["failed"] = stats.get("failed", 0) + 1
                    stats["error"] = str(e)[:300]
                new_lines += in_band
                continue
            pairs = _align([ln.text for ln in in_band], lines)
            prev_box = None
            pending: list[str] = []

            def flush(next_box):
                nonlocal pending
                if not pending:
                    return
                top = prev_box[3] + 2 if prev_box else by0 + 2
                bottom = next_box[1] - 2 if next_box else by1 - 2
                h = max(8.0, (bottom - top) / len(pending))
                for k, text in enumerate(pending):
                    lb = [bx0 + 4, top + k * h, bx1 - 4, top + (k + 1) * h - 1]
                    ws = _words_in_box(text, lb, rtl, conf=92.0)
                    new_lines.append(Line(text, ws, lb))
                pending = []

            for oi, aj in pairs:
                if oi is not None and aj is not None:
                    flush(in_band[oi].box)
                    ln = in_band[oi]
                    text = lines[aj]
                    ws = _words_in_box(text, ln.box, rtl)
                    new_lines.append(Line(text, ws, ln.box))
                    prev_box = ln.box
                elif aj is not None:
                    pending.append(lines[aj])
                else:
                    # OCR line the model did not return: usually a stamp fragment or noise; keep it, low confidence
                    ln = in_band[oi]
                    for w in ln.words:
                        w.conf = min(w.conf, 35.0)
                    flush(ln.box)
                    new_lines.append(ln)
                    prev_box = ln.box
            flush(None)
        new_lines.sort(key=lambda ln: (ln.box[1], ln.box[0]))
        reg.lines = new_lines
        return reg

    return reader
