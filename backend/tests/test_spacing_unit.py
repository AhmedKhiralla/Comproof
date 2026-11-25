"""Word-break findings on scans: the gap is measured on both prints before the OCR split is believed."""
from types import SimpleNamespace as N

from PIL import Image, ImageDraw, ImageFont

from app.engine import ingest, pipeline

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _print(words: list[str], space_px: int):
    """One line of text with a chosen word space; returns the page and the box of each word."""
    font = ImageFont.truetype(FONT, 34)
    im = Image.new("RGB", (900, 120), "white")
    d = ImageDraw.Draw(im)
    x, boxes = 20, []
    for w in words:
        b = d.textbbox((x, 40), w, font=font)
        d.text((x, 40), w, fill=(20, 20, 20), font=font)
        boxes.append([b[0], b[1], b[2], b[3]])
        x = b[2] + space_px
    doc = ingest.Document(name="x", kind="image", pages=[ingest.Page(index=0, image=im, source_dpi=300)])
    return doc, boxes


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def test_same_tight_space_is_an_ocr_split():
    ref, rb = _print(["Tetramethyl", "Acetyloctahydro"], 4)        # tight space on both prints
    des, db = _print(["Tetramethyl", "Acetyloctahydro"], 4)
    f = N(ref_hl=[(0, b) for b in rb], des_hl=[(0, _union(db))])  # OCR merged the words on the new print only
    assert pipeline.same_word_gaps(ref, des, f)


def test_removed_space_is_kept():
    ref, rb = _print(["Tetramethyl", "Acetyloctahydro"], 12)       # a normal word space
    des, db = _print(["TetramethylAcetyloctahydro"], 0)            # really printed without the space
    f = N(ref_hl=[(0, b) for b in rb], des_hl=[(0, db[0])])
    assert pipeline.same_word_gaps(ref, des, f) is None
