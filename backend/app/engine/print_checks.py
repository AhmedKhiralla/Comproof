"""Print checks on the test file: minimum text size, Braille, and dieline (folds and cut edges).

Text size
  Vector PDF: the size of every text line comes from the PDF itself.
  Scan or image: estimated from the height of the recognised lines and the scan resolution (labelled "estimated").
  Minimums are company settings per packaging type; the defaults follow the EU readability guideline
  (package leaflet 9 pt, other packaging 7 pt). Check each market's own rule.

Braille
  Dots are found as small round marks, grouped into 6-dot cells (2.5 mm dot pitch) and read as Grade 1 letters and
  numbers. The result is compared with the product name and strength. Embossed Braille often does not show on a
  flat scan, so "not found" on a scan is a prompt to check by touch, not a defect.

Dieline (vector PDF only)
  Thin straight stroked lines in one colour that frame the artwork are taken as the dieline; dashed (or inner)
  lines are folds. Text that crosses a fold, or comes within the safety margin of a cut edge, is reported.
"""
from __future__ import annotations

import math
import re

import numpy as np

DEFAULT_MIN_PT = {"leaflet": 9.0, "carton": 7.0, "label": 7.0, "sachet": 7.0, "blister_foil": 7.0, "tube": 7.0,
                  "other": 7.0}

# ---------------------------------------------------------------------------------------------- text size

def text_sizes(doc, regions, kind: str, min_pt: float | None) -> tuple[list[dict], dict]:
    """Lines printed below the minimum size. Returns (problems, stats)."""
    limit = float(min_pt or DEFAULT_MIN_PT.get(kind, 7.0))
    exact = doc.kind in ("pdf-vector", "docx")
    small: list[dict] = []
    sizes = []
    for r in regions:
        page = doc.pages[r.page] if r.page < len(doc.pages) else None
        if page is None:
            continue
        dpi = page.source_dpi if page.source_dpi and page.source_dpi > 72 else 300.0
        for ln in r.lines:
            txt = ln.text.strip()
            if len(re.sub(r"\W", "", txt)) < 4:
                continue
            hs = [w.box[3] - w.box[1] for w in ln.words if len(re.sub(r"\W", "", w.text)) >= 2]
            if not hs:
                continue
            h_px = float(np.median(hs))
            pt = h_px * 72.0 / dpi
            if not exact:
                pt *= 0.85              # recognised boxes include ascenders and descenders
            sizes.append(pt)
            threshold = limit - 0.3 if exact else limit * 0.85
            if pt < threshold:
                small.append({"page": r.page, "box": ln.box, "text": txt[:120], "pt": round(pt, 1), "lang": r.lang})
    stats = {"limit_pt": limit, "measured": "exact" if exact else "estimated",
             "median_pt": round(float(np.median(sizes)), 1) if sizes else None,
             "smallest_pt": round(float(min(sizes)), 1) if sizes else None, "lines": len(sizes)}
    # group neighbouring small lines on the same page into one problem
    problems: list[dict] = []
    for s in sorted(small, key=lambda x: (x["page"], x["box"][1])):
        last = problems[-1] if problems else None
        if last and last["page"] == s["page"] and s["box"][1] - last["box"][3] < 3 * (s["box"][3] - s["box"][1]):
            last["box"] = [min(last["box"][0], s["box"][0]), last["box"][1], max(last["box"][2], s["box"][2]), s["box"][3]]
            last["lines"] += 1
            last["pt"] = min(last["pt"], s["pt"])
            last["text"] = (last["text"] + " / " + s["text"])[:240]
        else:
            problems.append(dict(s, lines=1))
    return problems, stats


# ---------------------------------------------------------------------------------------------- Braille
BRAILLE = {  # dots -> letter (Grade 1 / UEB letters)
    (1,): "a", (1, 2): "b", (1, 4): "c", (1, 4, 5): "d", (1, 5): "e", (1, 2, 4): "f", (1, 2, 4, 5): "g",
    (1, 2, 5): "h", (2, 4): "i", (2, 4, 5): "j", (1, 3): "k", (1, 2, 3): "l", (1, 3, 4): "m", (1, 3, 4, 5): "n",
    (1, 3, 5): "o", (1, 2, 3, 4): "p", (1, 2, 3, 4, 5): "q", (1, 2, 3, 5): "r", (2, 3, 4): "s", (2, 3, 4, 5): "t",
    (1, 3, 6): "u", (1, 2, 3, 6): "v", (2, 4, 5, 6): "w", (1, 3, 4, 6): "x", (1, 3, 4, 5, 6): "y", (1, 3, 5, 6): "z",
    (3, 4, 5, 6): "#", (2,): ",", (2, 5, 6): ".", (3, 6): "-", (6,): "^", (2, 5): ":", (2, 3): ";", (2, 3, 5): "!",
    (4, 6): ".",   # decimal point in some codes (Marburg/EU) - shown as "."
    # French accented letters (Braille français); folded to their plain letter when comparing with the product name
    (1, 2, 3, 5, 6): "à", (1, 6): "â", (1, 2, 3, 4, 6): "ç", (1, 2, 3, 4, 5, 6): "é", (2, 3, 4, 6): "è",
    (1, 2, 6): "ê", (1, 2, 4, 6): "ë", (1, 4, 6): "î", (1, 2, 4, 5, 6): "ï", (1, 4, 5, 6): "ô", (2, 4, 6): "œ",
    (2, 3, 4, 5, 6): "ù", (1, 5, 6): "û", (1, 2, 5, 6): "ü",
}
DIGITS = dict(zip("abcdefghij", "1234567890"))


def find_dots(img, dpi: float) -> list[tuple[float, float, float]]:
    import cv2
    g = np.asarray(img.convert("L"))
    px_mm = dpi / 25.4
    # local contrast so embossing shadows and light-coloured dots both show
    # normalise local contrast so faint embossing shadows and light-coloured dots both show
    bg = cv2.GaussianBlur(g, (0, 0), 3 * px_mm).astype(np.float32)
    g = np.clip(128 + (g.astype(np.float32) - bg) * 4, 0, 255).astype(np.uint8)
    p = cv2.SimpleBlobDetector_Params()
    p.filterByArea = True
    p.minArea = math.pi * (0.45 * px_mm) ** 2
    p.maxArea = math.pi * (1.0 * px_mm) ** 2
    p.filterByCircularity = True
    p.minCircularity = 0.84          # round dots, not square barcode modules (0.785)
    p.filterByConvexity = True
    p.minConvexity = 0.85
    p.filterByInertia = True
    p.minInertiaRatio = 0.5
    p.minDistBetweenBlobs = 1.4 * px_mm
    det = cv2.SimpleBlobDetector_create(p)
    pts = [(k.pt[0], k.pt[1], k.size) for k in det.detect(g)]
    return pts


def read_braille(dots, dpi: float) -> list[dict]:
    """Group dots into Braille lines and cells and read them. Returns [{text, box, cells}]."""
    if len(dots) < 3:
        return []
    px_mm = dpi / 25.4
    pitch = 2.5 * px_mm
    tol = 0.35 * pitch
    # keep only dots that have a neighbour at about one dot pitch (Braille dots come in a grid)
    pts = np.array([(x, y) for x, y, _ in dots])
    keep = []
    for i, (x, y) in enumerate(pts):
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        if np.any((d > 0.6 * pitch) & (d < 2.7 * pitch)):
            keep.append((x, y))
    if len(keep) < 3:
        return []
    keep.sort(key=lambda p: p[1])
    rows: list[list] = []
    for x, y in keep:
        if rows and abs(rows[-1][0] - y) < tol:
            rows[-1][1].append(x)
            rows[-1][0] = (rows[-1][0] * (len(rows[-1][1]) - 1) + y) / len(rows[-1][1])
        else:
            rows.append([y, [x]])
    # group rows into lines of up to three rows one pitch apart
    lines, i = [], 0
    while i < len(rows):
        base = rows[i][0]
        grp = {0: rows[i][1]}
        j = i + 1
        while j < len(rows) and rows[j][0] - base < 2.5 * pitch:
            k = int(round((rows[j][0] - base) / pitch))
            if k in (1, 2):
                grp.setdefault(k, []).extend(rows[j][1])
            j += 1
        lines.append((base, grp))
        i = j
    out = []
    for base, grp in lines:
        xs = sorted(x for v in grp.values() for x in v)
        cols: list[float] = []
        for x in xs:
            if cols and abs(cols[-1] - x) < tol:
                continue
            cols.append(x)
        # pair columns into cells
        cells, c = [], 0
        while c < len(cols):
            if c + 1 < len(cols) and abs(cols[c + 1] - cols[c] - pitch) < tol:
                cells.append((cols[c], cols[c + 1]))
                c += 2
            else:
                cells.append((cols[c], cols[c] + pitch))
                c += 1
        text, number = "", False
        prev_right = None
        for left, right in cells:
            if prev_right is not None and left - prev_right > 1.8 * pitch * 1.6:
                text += " "
                number = False
            prev_right = right
            on = []
            for row_i in (0, 1, 2):
                for x in grp.get(row_i, []):
                    if abs(x - left) < tol:
                        on.append(row_i + 1)
                    elif abs(x - right) < tol:
                        on.append(row_i + 4)
            ch = BRAILLE.get(tuple(sorted(set(on))), "?")
            if ch == "#":
                number = True
                continue
            if ch == "^":
                continue
            if number and ch in DIGITS:
                ch = DIGITS[ch]
            elif ch not in ".,":
                number = False
            text += ch
        clean = text.replace(" ", "")
        if len(clean) >= 3 and clean.count("?") <= 0.2 * len(clean) and len(cells) >= 3:
            out.append({"text": text.strip(), "box": [int(cols[0] - pitch), int(base - pitch),
                                                     int(cols[-1] + pitch), int(base + 3 * pitch)],
                        "cells": len(cells)})
    return out


def braille_check(doc, expected_name: str, strengths: list[str], required: bool) -> tuple[list[dict], dict]:
    found = []
    for p in doc.pages:
        dpi = p.source_dpi if p.source_dpi and p.source_dpi > 72 else 300.0
        for b in read_braille(find_dots(p.image, dpi), dpi):
            found.append(dict(b, page=p.index))
    info = {"found": found, "expected": expected_name}
    problems = []
    import unicodedata
    fold = lambda s: unicodedata.normalize("NFKD", s.replace("œ", "oe")).encode("ascii", "ignore").decode()
    norm = lambda s: re.sub(r"[^a-z0-9.]", "", fold(s.lower()))
    joined = norm(" ".join(b["text"] for b in found))
    if not found:
        if required:
            if doc.kind == "pdf-vector":
                problems.append({"severity": "major", "title": "No Braille found",
                                 "detail": "Braille is required for this packaging, but no Braille dots were found on "
                                           "the artwork."})
            else:
                problems.append({"severity": "minor", "title": "Braille not visible on the scan",
                                 "detail": "No Braille was detected. Embossing often does not show on a flat scan: "
                                           "check the printed item by touch."})
        return problems, info
    name = norm(expected_name.split()[0]) if expected_name else ""
    if name and name not in joined:
        problems.append({"severity": "critical", "title": "Braille does not show the product name",
                         "detail": f"Braille reads “{' / '.join(b['text'] for b in found)}”; expected the name "
                                   f"“{expected_name}”.", "page": found[0]["page"], "box": found[0]["box"]})
    if strengths and not any(norm(s) in joined for s in strengths):
        problems.append({"severity": "major", "title": "Braille strength not found",
                         "detail": f"Braille reads “{' / '.join(b['text'] for b in found)}”; none of the registered "
                                   f"strengths ({', '.join(strengths)}) was read.",
                         "page": found[0]["page"], "box": found[0]["box"]})
    return problems, info


# ---------------------------------------------------------------------------------------------- dieline
def dieline_check(pdf_path: str, render_scale: float, margin_mm: float = 1.5) -> tuple[list[dict], dict]:
    import pdfplumber
    problems: list[dict] = []
    info: dict = {"found": False}
    pt_mm = 72 / 25.4
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            segs = []
            for o in page.lines + page.rects + page.curves:
                if not o.get("stroke", True) or o.get("fill") and o.get("object_type") == "rect":
                    continue
                if (o.get("linewidth") or 0) > 1.5:
                    continue
                pts = list(o.get("pts") or [(o["x0"], o["top"]), (o["x1"], o["bottom"])])
                if o.get("object_type") == "rect" and len(pts) >= 4:
                    pts.append(pts[0])                         # close the rectangle
                col = str(o.get("stroking_color"))
                dash = o.get("dash")
                dashed = bool(dash and dash[0])
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    if abs(x0 - x1) < 0.5 or abs(y0 - y1) < 0.5:
                        length = math.hypot(x1 - x0, y1 - y0)
                        if length >= 15 * pt_mm:
                            segs.append({"x0": min(x0, x1), "y0": min(y0, y1), "x1": max(x0, x1), "y1": max(y0, y1),
                                         "colour": col, "dashed": dashed})
            if not segs:
                continue
            by_col: dict = {}
            for s in segs:
                by_col.setdefault(s["colour"], []).append(s)
            W, Hh = float(page.width), float(page.height)
            best = None
            for col, ss in by_col.items():
                if col in ("(0,)", "(0, 0, 0, 1)", "(0, 0, 0)", "None"):       # black: artwork, not the die
                    continue
                x0 = min(s["x0"] for s in ss)
                x1 = max(s["x1"] for s in ss)
                y0 = min(s["y0"] for s in ss)
                y1 = max(s["y1"] for s in ss)
                span = ((x1 - x0) / W) * ((y1 - y0) / Hh)
                if span > 0.35 and (best is None or span > best[0]):
                    best = (span, col, ss, (x0, y0, x1, y1))
            if not best:
                continue
            _, col, ss, outer = best
            info.update(found=True, colour=col, page=pi)
            ox0, oy0, ox1, oy1 = outer
            on_edge = lambda s: (abs(s["x0"] - ox0) < 1 and abs(s["x1"] - ox0) < 1) or \
                (abs(s["x0"] - ox1) < 1 and abs(s["x1"] - ox1) < 1) or \
                (abs(s["y0"] - oy0) < 1 and abs(s["y1"] - oy0) < 1) or \
                (abs(s["y0"] - oy1) < 1 and abs(s["y1"] - oy1) < 1)
            any_dash = any(s["dashed"] for s in ss)
            folds = [s for s in ss if (s["dashed"] if any_dash else not on_edge(s))]
            cuts = [s for s in ss if s not in folds]
            info["folds"], info["cuts"] = len(folds), len(cuts)
            m = margin_mm * pt_mm
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            crossing, near = [], []
            for w in words:
                bx = (w["x0"], w["top"], w["x1"], w["bottom"])
                for s in folds:
                    if s["x0"] == s["x1"] and bx[0] < s["x0"] < bx[2] and bx[3] > s["y0"] and bx[1] < s["y1"]:
                        crossing.append(w)
                        break
                    if s["y0"] == s["y1"] and bx[1] < s["y0"] < bx[3] and bx[2] > s["x0"] and bx[0] < s["x1"]:
                        crossing.append(w)
                        break
                else:
                    for s in cuts:
                        if s["x0"] == s["x1"] and bx[3] > s["y0"] and bx[1] < s["y1"] and \
                                min(abs(bx[0] - s["x0"]), abs(bx[2] - s["x0"])) < m:
                            near.append(w)
                            break
                        if s["y0"] == s["y1"] and bx[2] > s["x0"] and bx[0] < s["x1"] and \
                                min(abs(bx[1] - s["y0"]), abs(bx[3] - s["y0"])) < m:
                            near.append(w)
                            break
            for ws, title, sev, what in ((crossing, "Text crosses a fold line", "major", "crosses a fold"),
                                         (near, "Text too close to a cut edge", "major",
                                          f"is within {margin_mm} mm of a cut edge")):
                if not ws:
                    continue
                x0 = min(w["x0"] for w in ws)
                y0 = min(w["top"] for w in ws)
                x1 = max(w["x1"] for w in ws)
                y1 = max(w["bottom"] for w in ws)
                problems.append({"severity": sev, "title": title, "page": pi,
                                 "detail": f"{len(ws)} word(s) {what}: " + " ".join(w["text"] for w in ws[:12]),
                                 "box": [x0 * render_scale, y0 * render_scale, x1 * render_scale, y1 * render_scale]})
    return problems, info
