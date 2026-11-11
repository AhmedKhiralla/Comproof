"""Page layout + OCR.

Turns each page image into text regions (columns / scanned half-pages) with word boxes,
language (eng/ara), and a record of what was deliberately excluded (stamps, signatures,
rotated print-house blocks, administrative headers, page numbers).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np
import pytesseract
from PIL import Image, ImageOps

# Administrative lines that are never part of the leaflet content.
# Matched fuzzily so OCR noise still hits. Tenants can extend this list.
DEFAULT_EXCLUDE_PHRASES = [
    "central administration for pharmaceutical care",
    "general administration of pharmaceutical references and leaflets",
    "leaflets administration",
    "according to pharmacology committee member on",
    "eda revision date",
    "revisor dr",
    "revisor",
    "scanned with camscanner",
]


@dataclass
class Word:
    text: str
    box: list            # x0, y0, x1, y1 in page pixels
    conf: float


@dataclass
class Line:
    text: str
    words: list
    box: list


@dataclass
class Region:
    page: int
    box: list
    lang: str            # "eng" or "ara"
    lines: list = field(default_factory=list)


@dataclass
class Exclusion:
    page: int
    box: list
    reason: str
    text: str = ""


# ---------------------------------------------------------------- preprocessing

def mask_colored_marks(img: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """Remove blue/violet ink (regulatory stamps, signatures) before OCR.
    Returns the cleaned grayscale image and a boolean mask of removed pixels."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    blue = (b - r > 35) & (b - g > 15)
    gray = np.asarray(img.convert("L")).copy()
    gray[blue] = 255
    gray = remove_rules(gray)
    return Image.fromarray(gray), blue


def remove_rules(gray: np.ndarray) -> np.ndarray:
    """Erase underlines and table rules (long thin horizontal strokes) that break OCR."""
    import cv2
    ink = (gray < 140).astype(np.uint8)
    k = max(60, gray.shape[1] // 25)       # longer than any Arabic baseline join
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    # keep only thin strokes (<= 4 px tall) so bold text bars are untouched
    thick = cv2.morphologyEx(lines, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    thin = (lines == 1) & (thick == 0)
    out = gray.copy()
    out[thin] = 255
    return out


def _runs(profile: np.ndarray, thr: float, min_gap: int) -> list[tuple[int, int]]:
    on = profile > thr
    runs, start, gap = [], None, 0
    for i, v in enumerate(on):
        if v:
            if start is None:
                start = i
            gap = 0
            end = i
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                runs.append((start, end + 1))
                start, gap = None, 0
    if start is not None:
        runs.append((start, end + 1))
    return runs


def split_spread(gray: Image.Image) -> list[int]:
    """Scanned two-page spreads: split at the gutter. Returns x boundaries."""
    w, h = gray.size
    if w < h * 1.15:
        return [0, w]
    ink = (np.asarray(gray) < 140).sum(0).astype(float)
    k = max(5, w // 150)
    sm = np.convolve(ink, np.ones(k) / k, mode="same")
    lo, hi = int(w * 0.38), int(w * 0.62)
    x = lo + int(np.argmin(sm[lo:hi]))
    if sm[x] < 0.2 * float(np.median(sm[sm > 1])):
        return [0, x, w]
    return [0, w]


def find_columns(gray: Image.Image) -> list[list[int]]:
    cols = []
    xs = split_spread(gray)
    for a, b in zip(xs, xs[1:]):
        for c in _find_columns(gray.crop((a, 0, b, gray.height))):
            cols.append([c[0] + a, c[1], c[2] + a, c[3]])
    return cols


def _find_columns(gray: Image.Image) -> list[list[int]]:
    """Text columns via vertical whitespace. Thin rules and specks are dropped."""
    ink = np.asarray(gray) < 140
    h, w = ink.shape
    prof = ink.sum(0).astype(float)
    k = max(3, w // 600)
    prof = np.convolve(prof, np.ones(k) / k, mode="same")
    min_gap = max(8, int(w * 0.004))
    cols = []
    nz = prof[prof > 1]
    thr = max(8.0, 0.06 * float(np.median(nz))) if len(nz) else 8.0
    for x0, x1 in _runs(prof, thr=thr, min_gap=min_gap):
        if x1 - x0 < w * 0.06:          # vertical rules, cut marks
            continue
        sub = ink[:, x0:x1]
        rows = np.where(sub.sum(1) > 2)[0]
        if len(rows) == 0:
            continue
        cols.append([x0, int(rows[0]), x1, int(rows[-1]) + 1])
    return cols


def _is_rotated(crop: Image.Image) -> bool:
    try:
        osd = pytesseract.image_to_osd(crop, config="--psm 0")
        m = re.search(r"Orientation in degrees: (\d+)", osd)
        c = re.search(r"Orientation confidence: ([\d.]+)", osd)
        return bool(m and int(m.group(1)) in (90, 270) and c and float(c.group(1)) > 2)
    except pytesseract.TesseractError:
        return False


def _ocr_conf(crop: Image.Image, lang: str) -> float:
    d = pytesseract.image_to_data(crop, lang=lang, config="--psm 4", output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, t in zip(d["conf"], d["text"]) if t.strip() and float(c) >= 0]
    if lang == "ara":
        arabic = sum(1 for t in d["text"] for ch in t if "؀" <= ch <= "ۿ")
        total = sum(len(t) for t in d["text"]) or 1
        if arabic / total < 0.5:
            return 0.0
    return float(np.mean(confs)) if confs else 0.0


def detect_lang(crop: Image.Image, latin: str = "eng") -> str:
    """Arabic or Latin script? `latin` is the comparison's Latin OCR language: "eng", "fra" or "eng+fra"."""
    h = crop.height
    top = int(h * 0.3)
    band = crop.crop((0, top, crop.width, min(h, top + max(300, h // 4))))
    return "ara" if _ocr_conf(band, "ara") > _ocr_conf(band, latin) + 5 else latin


# English or French? Scored on stopwords plus accented letters; used only when a comparison carries both.
FR_STOP = {"le", "la", "les", "des", "du", "de", "un", "une", "et", "ou", "vous", "votre", "vos", "ne", "pas",
           "est", "sont", "ce", "cette", "ces", "avec", "pour", "dans", "sur", "si", "que", "qui", "plus",
           "avant", "chez", "prenez", "prendre", "médicament", "notice", "effets", "indésirables", "jour",
           "jours", "comprimé", "comprimés", "grossesse", "conserver", "contre", "autres", "pendant", "chaque",
           "votre", "être", "aux", "au", "dose", "enfants", "mois", "sans", "peut", "doit", "lisez"}
EN_STOP = {"the", "of", "and", "or", "you", "your", "not", "is", "are", "this", "these", "with", "for", "in",
           "on", "if", "that", "which", "more", "before", "take", "taking", "medicine", "leaflet", "effects",
           "side", "day", "days", "tablet", "tablets", "pregnancy", "store", "other", "during", "each", "any",
           "do", "to", "it", "as", "by", "have", "has", "been", "children", "month", "without", "can", "must"}
FR_HINT = set("éèêëàâçîïôùûüœ")


def latin_lang_of(text: str) -> str:
    low = text.lower()
    words = re.findall(r"[a-zà-ÿœ']+", low)
    fr = 2 * sum(1 for w in words if w in FR_STOP) + sum(1 for ch in low if ch in FR_HINT)
    en = 2 * sum(1 for w in words if w in EN_STOP)
    return "fra" if fr > en else "eng"


def resolve_latin(reg: "Region", latin: str) -> "Region":
    """Fix a region's language after reading: Arabic stays; Latin becomes the one Latin language of the
    comparison, or, when both English and French are present, whichever its own wording scores as."""
    if reg.lang != "ara":
        reg.lang = latin_lang_of(" ".join(ln.text for ln in reg.lines)) if "+" in latin else latin
    return reg


# ---------------------------------------------------------------- OCR

def _scale_for(crop: Image.Image, lang: str) -> float:
    d = pytesseract.image_to_data(crop.crop((0, 0, crop.width, min(crop.height, 600))), lang=lang,
                                  config="--psm 4", output_type=pytesseract.Output.DICT)
    hs = [hh for hh, t in zip(d["height"], d["text"]) if t.strip() and hh > 4]
    med = float(np.median(hs)) if hs else 30.0
    return 1.0 if med >= 20 else min(3.0, 26.0 / med)


def _bands(gray: Image.Image, box: list, target: int = 450) -> list[list[int]]:
    """Cut a tall column into horizontal chunks at blank rows (never through a text line)."""
    x0, y0, x1, y1 = box
    ink = (np.asarray(gray.crop((x0, y0, x1, y1))) < 140).sum(1)
    blank = ink <= 1
    cuts, last = [0], 0
    while last + target < len(ink):
        lo, hi = last + int(target * 0.6), min(len(ink), last + int(target * 1.4))
        cand = [i for i in range(lo, hi) if blank[i]]
        if not cand:
            cut = hi
        else:
            mid = last + target
            cut = min(cand, key=lambda i: abs(i - mid))
        cuts.append(cut)
        last = cut
    cuts.append(len(ink))
    return [[x0, y0 + a, x1, y0 + b] for a, b in zip(cuts, cuts[1:]) if b - a > 5]


def ocr_region(gray: Image.Image, box: list, lang: str, page: int) -> Region:
    x0, y0, x1, y1 = box
    s = _scale_for(gray.crop((x0, y0, x1, y1)), lang)
    reg = Region(page=page, box=box, lang=lang)
    psm = "6" if lang == "ara" else "4"
    for bx0, by0, bx1, by1 in _bands(gray, box):
        crop = gray.crop((bx0, by0, bx1, by1))
        if s != 1.0:
            crop = crop.resize((int(crop.width * s), int(crop.height * s)), Image.LANCZOS)
        crop = ImageOps.autocontrast(crop)
        d = pytesseract.image_to_data(crop, lang=lang, config=f"--psm {psm}",
                                      output_type=pytesseract.Output.DICT)
        lines: dict = {}
        for i, t in enumerate(d["text"]):
            if not t.strip():
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            wb = [bx0 + d["left"][i] / s, by0 + d["top"][i] / s,
                  bx0 + (d["left"][i] + d["width"][i]) / s, by0 + (d["top"][i] + d["height"][i]) / s]
            lines.setdefault(key, []).append(Word(t, wb, float(d["conf"][i])))
        for key in sorted(lines, key=lambda k: (min(w.box[1] for w in lines[k]), k)):
            ws = sorted(lines[key], key=lambda w: -w.box[0] if lang == "ara" else w.box[0])
            ws = [w for i, w in enumerate(ws) if i == 0 or w.text != ws[i - 1].text]
            lb = [min(w.box[0] for w in ws), min(w.box[1] for w in ws),
                  max(w.box[2] for w in ws), max(w.box[3] for w in ws)]
            reg.lines.append(Line(" ".join(w.text for w in ws), ws, lb))
    return reg


# ---------------------------------------------------------------- exclusions

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def is_admin_line(text: str, phrases: list[str]) -> bool:
    if not re.search(r"[A-Za-z0-9\u0600-\u06ff\u0660-\u0669]", text):
        return True                                  # pure punctuation / OCR specks
    t = _norm(text)
    if not t:
        return False                                 # Arabic content line
    if re.fullmatch(r"\d{1,3}", t):                 # page numbers
        return True
    for p in phrases:
        if p in t:
            return True
        if abs(len(t) - len(p)) <= 0.35 * len(p) and SequenceMatcher(None, p, t).ratio() > 0.8:
            return True
    return False


AR_STOP = {"في", "من", "على", "او", "أو", "لا", "إذا", "اذا", "هذا", "مع", "عن", "إلى", "الى", "قد", "أن", "ان", "ما", "التي", "الذي"}


def _arabic_ok(words: list[str]) -> float:
    toks = [w.strip(".,:;()") for w in words]
    return sum(t in AR_STOP for t in toks) / max(1, len(toks))


def region_from_words(words: list, box: list, page: int, lang: str):
    """Build a region from exact PDF text-layer words. Returns None when the Arabic text layer is
    unusable (wrong order or unmapped glyphs) so the caller falls back to OCR."""
    import unicodedata
    x0, y0, x1, y1 = box
    inside = [w for w in words if x0 - 2 <= (w["box"][0] + w["box"][2]) / 2 <= x1 + 2
              and y0 - 2 <= (w["box"][1] + w["box"][3]) / 2 <= y1 + 2]
    if not inside:
        return None
    if lang == "ara":
        texts = [unicodedata.normalize("NFKC", w["text"]) for w in inside]
        as_is, rev = _arabic_ok(texts), _arabic_ok([t[::-1] for t in texts])
        if max(as_is, rev) < 0.03:
            return None
        flip = rev > as_is
        for w, t in zip(inside, texts):
            w["text"] = t[::-1] if flip else t
    else:
        for w in inside:
            w["text"] = unicodedata.normalize("NFKC", w["text"])
    inside.sort(key=lambda w: (w["box"][1], w["box"][0]))
    lines: list[list] = []
    for w in inside:
        h = w["box"][3] - w["box"][1]
        cy = (w["box"][1] + w["box"][3]) / 2
        if lines:
            last = lines[-1]
            ly0 = min(v["box"][1] for v in last)
            ly1 = max(v["box"][3] for v in last)
            if ly0 - h * 0.3 <= cy <= ly1 + h * 0.3:
                last.append(w)
                continue
        lines.append([w])
    reg = Region(page=page, box=box, lang=lang)
    for ln in lines:
        ws = sorted(ln, key=lambda w: -w["box"][0] if lang == "ara" else w["box"][0])
        items = [Word(w["text"], [float(v) for v in w["box"]], 100.0) for w in ws]
        lb = [min(w.box[0] for w in items), min(w.box[1] for w in items),
              max(w.box[2] for w in items), max(w.box[3] for w in items)]
        reg.lines.append(Line(" ".join(w.text for w in items), items, lb))
    return reg


def _rotation(crop: Image.Image) -> int:
    """Degrees to rotate clockwise so the text is upright (0, 90, 180 or 270)."""
    try:
        osd = pytesseract.image_to_osd(crop, config="--psm 0")
        m = re.search(r"Rotate: (\d+)", osd)
        c = re.search(r"Orientation confidence: ([\d.]+)", osd)
        if m and c and float(c.group(1)) > 2:
            return int(m.group(1)) % 360
    except pytesseract.TesseractError:
        pass
    return 0


def ocr_rotated(gray: Image.Image, box: list, page: int, rotate: int, latin: str = "eng") -> Region:
    """Read a rotated block (side panel of a carton, vertical label text) and map positions back."""
    x0, y0, x1, y1 = box
    crop = gray.crop((x0, y0, x1, y1))
    W, H = crop.size
    up = crop.rotate(-rotate, expand=True)          # PIL rotates counter-clockwise
    lang = detect_lang(up, latin)
    reg = ocr_region(up, [0, 0, up.width, up.height], lang, page)

    def back(px, py):
        if rotate == 90:          # clockwise 90: (x, y) -> (H-1-y, x)
            return py, H - 1 - px
        if rotate == 270:         # clockwise 270: (x, y) -> (y, W-1-x)
            return W - 1 - py, px
        if rotate == 180:
            return W - 1 - px, H - 1 - py
        return px, py

    def map_box(b):
        (ax, ay), (bx, by) = back(b[0], b[1]), back(b[2], b[3])
        return [x0 + min(ax, bx), y0 + min(ay, by), x0 + max(ax, bx), y0 + max(ay, by)]

    for ln in reg.lines:
        for w in ln.words:
            w.box = map_box(w.box)
        ln.box = map_box(ln.box)
    reg.box = box
    return reg


def analyse_page(img: Image.Image, page: int, exclude_phrases: list[str] | None = None, *,
                 text_words: list | None = None, rotated: str = "ignore", reader=None, latin: str = "eng"):
    """Find the text regions of one page and read them.

    text_words  exact words from a PDF text layer (positions in page pixels); OCR is used only where
                the text layer is missing or unusable.
    rotated     "ignore" leaves rotated blocks out (print-house strips on leaflets);
                "read" turns them upright and reads them (side panels of cartons, labels).
    reader      optional callable(gray, region) -> region that replaces OCR text with AI reading.
    """
    phrases = [p.lower() for p in (exclude_phrases or DEFAULT_EXCLUDE_PHRASES)]
    gray, stamp_mask = mask_colored_marks(img)
    exclusions: list[Exclusion] = []
    if stamp_mask.sum() > 500:
        ys, xs = np.where(stamp_mask)
        exclusions.append(Exclusion(page, [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                                    "Stamp / signature ink removed (blue)"))
    regions: list[Region] = []
    vocab = _admin_vocab(phrases)
    for box in find_columns(gray):
        crop = gray.crop(tuple(box))
        if crop.height > crop.width * 1.6 or crop.width > crop.height * 4:
            rot = _rotation(crop) if crop.height > crop.width * 1.6 else 0
            if rot in (90, 270):
                if rotated == "ignore":
                    exclusions.append(Exclusion(page, box, "Rotated block (print-house / artwork info)"))
                    continue
                reg = resolve_latin(ocr_rotated(gray, box, page, rot, latin), latin)
                if reader is not None:
                    reg = reader(gray, reg, rot)
                reg.lines = [ln for ln in reg.lines if not is_admin_line(ln.text, phrases)]
                if reg.lines:
                    regions.append(reg)
                continue
        box = _cut_header(gray, box, phrases, vocab, exclusions, page)
        crop = gray.crop(tuple(box))
        reg = None
        if text_words:
            inside = [w for w in text_words if box[0] <= (w["box"][0] + w["box"][2]) / 2 <= box[2]
                      and box[1] <= (w["box"][1] + w["box"][3]) / 2 <= box[3]]
            ar = sum(1 for w in inside for ch in w["text"] if "\u0600" <= ch <= "\u06ff" or "\ufb50" <= ch <= "\ufeff")
            total = sum(len(w["text"]) for w in inside) or 1
            lang = "ara" if ar / total > 0.4 else latin
            reg = region_from_words(inside, box, page, lang)
            if reg is not None:
                reg = resolve_latin(reg, latin)
        if reg is None:
            lang = detect_lang(crop, latin)
            reg = resolve_latin(ocr_region(gray, box, lang, page), latin)
            if reader is not None:
                reg = reader(gray, reg, 0)
        pn_y = _page_number_y(reg.lines, img.height)
        kept = []
        for ln in reg.lines:
            if pn_y is not None and ln.box[1] >= pn_y - 2:
                exclusions.append(Exclusion(page, ln.box, "Footer (page number / signature)", ln.text))
                continue
            confs = [w.conf for w in ln.words if w.conf >= 0]
            if confs and np.mean(confs) < 40:
                exclusions.append(Exclusion(page, ln.box, "Unreadable line (stamp, handwriting or scan damage)",
                                            ln.text))
                continue
            header_zone = ln.box[1] < img.height * 0.12
            if (is_admin_line(ln.text, phrases) or _is_signature(ln)
                    or (header_zone and is_partial_admin(ln.text, vocab))):
                exclusions.append(Exclusion(page, ln.box, "Administrative header/footer", ln.text))
            else:
                kept.append(ln)
        reg.lines = _drop_footer(kept, exclusions, page, img.height)
        if reg.lines:
            regions.append(reg)
    return regions, exclusions, gray


PRINT_CODE = re.compile(r"^\s*(\d{4,}|[A-Z0-9]{2,}\d[A-Z0-9]{4,})\W*\w{0,3}\s*$")


def _admin_vocab(phrases):
    return {w for p in phrases for w in p.split() if len(w) > 2}


def is_partial_admin(text: str, vocab: set) -> bool:
    ws = [w for w in _norm(text).split() if len(w) > 2]
    return len(ws) >= 2 and sum(w in vocab for w in ws) / len(ws) >= 0.6


def _page_number_y(lines, page_h):
    ys = [ln.box[1] for ln in lines
          if re.fullmatch(r"\s*\d{1,3}\s*", ln.text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
          and ln.box[1] > page_h * 0.72]
    return min(ys) if ys else None


def _cut_header(gray, box, phrases, vocab, exclusions, page):
    """Read the top band of a region in English: regulatory headers are English even on
    Arabic pages. Move the region top below any administrative lines found there."""
    x0, y0, x1, y1 = box
    band_h = int(gray.height * 0.13) - y0
    if band_h < 30:
        return box
    d = pytesseract.image_to_data(gray.crop((x0, y0, x1, y0 + band_h)), lang="eng", config="--psm 4",
                                  output_type=pytesseract.Output.DICT)
    lines: dict = {}
    for i, t in enumerate(d["text"]):
        if t.strip():
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            lines.setdefault(key, []).append((t, d["top"][i] + d["height"][i]))
    cut = None
    for ws in lines.values():
        text = " ".join(w for w, _ in ws)
        if is_admin_line(text, phrases) and re.search("[A-Za-z]", text) or is_partial_admin(text, vocab):
            bottom = y0 + max(b for _, b in ws) + 4
            cut = bottom if cut is None else max(cut, bottom)
            exclusions.append(Exclusion(page, [x0, y0, x1, bottom], "Regulatory header (EDA admin text)", text))
    return [x0, cut, x1, y1] if cut else box


def _drop_footer(lines, exclusions, page, page_h):
    """Everything below a page number (signatures, scanner marks) is footer;
    print-house job codes are tracking info, not content."""
    out = []
    pn_y = None
    for ln in lines:
        if re.fullmatch(r"\s*\d{1,3}\s*", ln.text) and ln.box[1] > page_h * 0.75:
            pn_y = ln.box[1] if pn_y is None else min(pn_y, ln.box[1])
    for ln in lines:
        if pn_y is not None and ln.box[1] >= pn_y - 2:
            exclusions.append(Exclusion(page, ln.box, "Footer (page number / signature)", ln.text))
        elif PRINT_CODE.match(ln.text):
            exclusions.append(Exclusion(page, ln.box, "Print-house tracking code", ln.text))
        else:
            out.append(ln)
    return out


def _is_signature(ln: Line) -> bool:
    """Handwritten notes OCR as low-confidence junk; drop short, very low-confidence lines."""
    confs = [w.conf for w in ln.words if w.conf >= 0]
    return bool(confs) and np.mean(confs) < 35 and len(ln.words) <= 4
