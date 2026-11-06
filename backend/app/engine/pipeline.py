"""Runs the three audit levels end to end and writes screenshots and a JSON result.

Level 1  scientific and internal-consistency audit of the approved text
Level 2  full-document content comparison, every word, per language
Level 3  punctuation, spacing, capitalisation and digit style on matching text
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageOps

from . import ai, compare, ingest, layout, master_checks

ENGINE_VERSION = "2.0.0"
SEV_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}
KIND_LABELS = {"leaflet": "patient leaflet / SmPC", "carton": "carton", "label": "label", "sachet": "sachet",
               "blister_foil": "blister foil", "tube": "tube", "other": "packaging text"}


class Cancelled(Exception):
    pass


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _analyse(doc: ingest.Document, phrases, progress, label, rotated, reader, check):
    regions, exclusions = [], []
    workers = 2 if reader else min(4, os.cpu_count() or 2)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(layout.analyse_page, p.image, p.index, phrases, text_words=p.words,
                          rotated=rotated, reader=reader) for p in doc.pages]
        for i, f in enumerate(futs):
            regs, exc, _ = f.result()
            regions += regs
            exclusions += exc
            progress(f"{label}: page {i + 1} of {len(doc.pages)} read")
            check()
    return regions, exclusions


PROOF_RED = (200, 16, 46)
PROOF_BLUE = (29, 95, 168)


def crop(doc: ingest.Document, loc: list, hl: list, anchor: list, colour, pad: int = 30, max_h: int = 760):
    """Screenshot of the finding: the lines in context (light tint), the exact words that differ
    (strong box + underline), and a caret where missing text belongs."""
    pts = loc or anchor
    if not pts:
        return None, []
    page = pts[0][0]
    if page < 0 or page >= len(doc.pages):
        return None, []
    img = doc.pages[page].image
    boxes = [b for p, b in (loc + anchor) if p == page]
    words = [b for p, b in hl if p == page]
    focus = words or boxes
    x0 = max(0, min(b[0] for b in boxes) - pad)
    x1 = min(img.width, max(b[2] for b in boxes) + pad)
    y0 = max(0, min(b[1] for b in boxes) - pad)
    y1 = min(img.height, max(b[3] for b in boxes) + pad)
    if y1 - y0 > max_h:                      # keep the differing words in view
        fy = min(b[1] for b in focus)
        y0 = max(0, fy - max_h // 3)
        y1 = min(img.height, y0 + max_h)
    c = img.crop((x0, y0, x1, y1)).convert("RGBA")
    ov = Image.new("RGBA", c.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for b in [b for p, b in loc if p == page]:
        d.rectangle([b[0] - x0 - 4, b[1] - y0 - 3, b[2] - x0 + 4, b[3] - y0 + 3], fill=colour + (18,))
    for b in words:
        d.rectangle([b[0] - x0 - 2, b[1] - y0 - 2, b[2] - x0 + 2, b[3] - y0 + 2],
                    fill=colour + (46,), outline=colour + (235,), width=2)
        d.line([b[0] - x0 - 2, b[3] - y0 + 4, b[2] - x0 + 2, b[3] - y0 + 4], fill=colour + (255,), width=3)
    for p, b in anchor:
        if p != page:
            continue
        cx, cy = b[2] - x0 + 6, b[3] - y0 + 2
        hgt = max(10, (b[3] - b[1]) // 2)
        d.polygon([(cx, cy - hgt), (cx - hgt * 0.7, cy + 2), (cx + hgt * 0.7, cy + 2)], fill=colour + (230,))
        d.line([cx, b[1] - y0 - 4, cx, cy], fill=colour + (230,), width=3)
    return Image.alpha_composite(c, ov).convert("RGB"), [page, x0, y0, x1, y1]


def _enrich_step1(findings, ref_regions):
    """Give Step 1 findings a section, location and action like the others."""
    toks = compare.tokens_from_regions(ref_regions, "eng")
    actions = {
        "consistency": "Correct the approved leaflet through change control before it is used as the master.",
        "data": "Verify against the source reference (WHO ATC index / originator SmPC) and correct the master.",
        "structure": "Check the master leaflet structure against the EDA SmPC/PIL template.",
        "typography": "Correct the typo in the master leaflet.",
        "ai_science": "Review with the regulatory pharmacist and correct the master if confirmed.",
    }
    for f in findings:
        if f.ref_loc:
            p, b = f.ref_loc[0]
            inside = [t for t in toks if t.page == p and t.box[1] >= b[1] - 5 and t.box[3] <= b[3] + 5
                      and t.box[0] >= b[0] - 5 and t.box[2] <= b[2] + 5]
            if inside:
                f.section = inside[0].section
                f.where_ref = compare.where(inside, "approved")
                f.ref_hl = [(t.page, [int(v) for v in t.box]) for t in inside[:1]] if f.kind == "typography" else []
        f.category = "Master leaflet" if f.kind != "ai_science" else "AI scientific review"
        f.explanation = (f.note + " " if f.note else "") + {
            "consistency": "The approved leaflet contradicts itself; the design team cannot know which is right.",
            "data": "Reference data in the approved leaflet looks incomplete or malformed.",
            "structure": "The approved leaflet's structure has a defect.",
            "typography": "A typo in the master will be copied into every artwork made from it.",
        }.get(f.kind, "")
        f.action = actions.get(f.kind, "Review.")


def run(ref_path: str, des_path: str, out_dir: str, settings: dict | None = None, progress=print,
        cancelled=lambda: False) -> dict:
    """settings: kind, languages, step1, step3, exclude_phrases, rotated_text, mirror_test,
    ai: {provider, reading_provider, review, science, read}."""
    settings = settings or {}
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()

    def check():
        if cancelled():
            raise Cancelled()

    kind = settings.get("kind") or "leaflet"
    languages = settings.get("languages") or ["eng", "ara"]
    phrases = layout.DEFAULT_EXCLUDE_PHRASES + [p.lower() for p in settings.get("exclude_phrases", [])]
    rotated = settings.get("rotated_text") or "auto"
    if rotated == "auto":
        rotated = "ignore" if kind == "leaflet" else "read"
    ai_cfg = settings.get("ai") or {}
    review_p = ai.pick(ai_cfg.get("provider")) if (ai_cfg.get("review") or ai_cfg.get("science")) else None
    read_p = ai.pick(ai_cfg.get("reading_provider") or ai_cfg.get("provider")) if ai_cfg.get("read") else None
    ai_info = {"review_provider": review_p.name if review_p and ai_cfg.get("review") else None,
               "science_provider": review_p.name if review_p and ai_cfg.get("science") else None,
               "reading_provider": read_p.name if read_p else None,
               "vision_model": None, "science_model": None, "reading_model": None, "notes": []}

    progress("Loading documents")
    ref, des = ingest.load(ref_path), ingest.load(des_path)
    if settings.get("mirror_test"):
        for p in des.pages:
            p.image = ImageOps.mirror(p.image)
            p.words = None
    check()

    read_stats: dict = {}
    reader = None
    if read_p:
        from .ai_read import make_reader
        reader = make_reader(read_p, read_stats, threading.Lock())
    ref_regions, ref_ex = _analyse(ref, phrases, progress, "Approved", rotated, reader, check)
    des_regions, des_ex = _analyse(des, phrases, progress, "Design", rotated, reader, check)
    if read_p:
        ai_info["reading_model"] = read_stats.get("model")
        ai_info["tiles_read"] = read_stats.get("tiles", 0)
        if read_stats.get("failed"):
            ai_info["notes"].append(f"AI reading failed on {read_stats['failed']} tiles; OCR text was used there "
                                    f"({read_stats.get('error', '')}).")

    findings: list[compare.Finding] = []
    # ---- Level 1: approved text audit
    if settings.get("step1", True):
        progress("Level 1: auditing the approved text")
        findings = master_checks.run(ref_regions)
        _enrich_step1(findings, ref_regions)
        if review_p and ai_cfg.get("science"):
            progress("Level 1: AI scientific review")
            try:
                eng = "\n".join(l.text for r in ref_regions if r.lang == "eng" for l in r.lines)
                ara = "\n".join(l.text for r in ref_regions if r.lang == "ara" for l in r.lines)
                ai_info["science_model"], issues = ai.science(review_p, eng, ara, KIND_LABELS.get(kind, kind))
                for k, it in enumerate(issues, 1):
                    sev = it.get("severity") if it.get("severity") in ("critical", "major", "minor") else "minor"
                    lang = "ara" if it.get("language") == "ar" else "eng"
                    regs = [r for r in ref_regions if r.lang == lang] or ref_regions
                    f = compare.Finding(f"A{k}", 1, lang, "ai_science", sev, str(it.get("problem", "AI finding"))[:200],
                                        str(it.get("quote", "")), "", _locate(regs, str(it.get("quote", ""))), [], 1.0,
                                        False, None, str(it.get("suggestion", "")))
                    f.section = str(it.get("section", ""))[:120]
                    f.category = "AI scientific review"
                    f.explanation = f.title
                    f.action = f.note or "Review with the regulatory pharmacist and correct the master if confirmed."
                    findings.append(f)
            except ai.AIUnavailable as e:
                ai_info["notes"].append(f"AI scientific review was skipped: {e}")
        check()

    # ---- Levels 2 and 3, per language
    order = {}
    for lang in [l for l in ("eng", "ara") if l in languages]:
        if ref.plain_text is not None:
            a = compare.tokens_from_text("\n".join(l for l in ref.plain_text.splitlines()
                                                   if compare.is_arabic(l) == (lang == "ara")), lang)
            b = compare.tokens_from_regions(des_regions, lang)
            ratio, ro, do = 0, "text", "ltr"
        else:
            best = compare.best_order(ref_regions, des_regions, lang)
            if not best:
                continue
            ratio, a, b, ro, do = best
        order[lang] = {"approved": ro, "design": do, "similarity": round(ratio, 3),
                       "approved_words": len(a), "design_words": len(b)}
        progress(f"Level 2: comparing {'Arabic' if lang == 'ara' else 'English'} text")
        content, spacing = compare.diff(a, b, lang, start_id=len(findings) + 1)
        findings += content
        if settings.get("step3", True):
            progress(f"Level 3: punctuation and typography ({'Arabic' if lang == 'ara' else 'English'})")
            findings += spacing
            findings += compare.typography(a, b, lang, start_id=len(findings) + 1)
        check()

    # ---- second look at OCR text: re-read each flagged spot at higher resolution
    exact = ref.kind == "pdf-vector" and des.kind == "pdf-vector"
    if not exact and not read_p:
        progress("Re-reading flagged spots to remove OCR noise")
        for f in findings:
            if f.step == 2 and f.severity != "info":
                verdict = reread(ref, des, f)
                if verdict:
                    f.note = verdict
                    f.severity = "info"
        check()

    # ---- screenshots
    progress("Creating screenshots")
    shots = os.path.join(out_dir, "shots")
    os.makedirs(shots, exist_ok=True)
    crops = {}
    for f in findings:
        rc, f.ref_crop = crop(ref, f.ref_loc, f.ref_hl, f.ref_anchor, PROOF_RED)
        dc, f.des_crop = crop(des, f.des_loc, f.des_hl, f.des_anchor, PROOF_BLUE if f.step != 1 else PROOF_RED)
        crops[f.id] = (rc, dc)
        if rc is not None:
            rc.save(os.path.join(shots, f"{f.id}_approved.jpg"), quality=88)
        if dc is not None:
            dc.save(os.path.join(shots, f"{f.id}_design.jpg"), quality=88)

    # ---- AI review of each comparison finding
    if review_p and ai_cfg.get("review"):
        todo = [f for f in findings if f.step in (2, 3) and f.needs_ai]
        done = [0]
        lock = threading.Lock()

        def one(f):
            rc, dc = crops[f.id]
            try:
                f.ai = ai.review(review_p, rc, dc, f.ref_text, f.des_text, f.lang)
                if f.ai.get("verdict") == "ocr_noise":
                    f.severity = "info"
                elif f.ai.get("verdict") == "real_difference" and f.ai.get("impact") in SEV_ORDER:
                    f.severity = min(f.severity, f.ai["impact"], key=lambda s: SEV_ORDER.get(s, 3))
                    if f.severity == "info":
                        f.severity = "minor"
            except ai.AIUnavailable as e:
                f.ai = {"verdict": "unclear", "explanation": f"AI review unavailable: {e}"}
            with lock:
                done[0] += 1
                if done[0] % 5 == 0 or done[0] == len(todo):
                    progress(f"AI review {done[0]} of {len(todo)}")

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(one, todo))
        ai_info["vision_model"] = next((f.ai.get("model") for f in todo if f.ai and f.ai.get("model")), None)
        check()

    # ---- page previews for the interactive viewer
    for tag, doc in (("approved", ref), ("design", des)):
        for p in doc.pages:
            im = p.image.copy()
            im.thumbnail((2400, 2400))
            im.save(os.path.join(shots, f"{tag}_p{p.index}.jpg"), quality=80)

    findings.sort(key=lambda f: (f.step, SEV_ORDER.get(f.severity, 3)))
    manifest = {name: sha256(os.path.join(shots, name)) for name in sorted(os.listdir(shots))}
    result = {
        "engine_version": ENGINE_VERSION,
        "kind": kind,
        "approved": {"name": ref.name, "kind": ref.kind, "pages": len(ref.pages), "sha256": sha256(ref_path),
                     "sizes": [p.image.size for p in ref.pages]},
        "design": {"name": des.name, "kind": des.kind, "pages": len(des.pages), "sha256": sha256(des_path),
                   "sizes": [p.image.size for p in des.pages]},
        "settings": {k: v for k, v in settings.items() if k != "ai"} | {"rotated_text_used": rotated},
        "reading_order": order,
        "ai": ai_info,
        "exclusions": [dataclasses.asdict(e) | {"doc": "approved"} for e in ref_ex]
                      + [dataclasses.asdict(e) | {"doc": "design"} for e in des_ex],
        "findings": [dataclasses.asdict(f) for f in findings],
        "screenshots": manifest,
        "seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    progress("Done")
    return result


def _read_loc(doc, loc, lang, grow=0):
    import pytesseract
    from PIL import ImageOps
    out = []
    for page, b in loc:
        if page < 0 or page >= len(doc.pages):
            continue
        img = doc.pages[page].image
        h = b[3] - b[1]
        box = (max(0, b[0] - 6), max(0, b[1] - 6 - grow * h), min(img.width, b[2] + 6),
               min(img.height, b[3] + 6 + grow * h))
        gray, _ = layout.mask_colored_marks(img.crop(box))
        s = 2 if gray.height < 400 else 1
        gray = ImageOps.autocontrast(gray.resize((gray.width * s, gray.height * s), Image.LANCZOS))
        out.append(pytesseract.image_to_string(gray, lang=lang, config="--psm 6"))
    toks = []
    for w in " ".join(out).split():
        toks += compare.norm_word(w, lang)
    return "".join(toks)


def reread(ref, des, f) -> str:
    """Returns a note when a closer read shows both documents say the same thing."""
    from difflib import SequenceMatcher
    target_r = "".join(t for w in f.ref_text.split() for t in compare.norm_word(w, f.lang))
    target_d = "".join(t for w in f.des_text.split() for t in compare.norm_word(w, f.lang))
    if f.kind in ("changed", "numeric", "ocr"):
        r, d = _read_loc(ref, f.ref_loc, f.lang), _read_loc(des, f.des_loc, f.lang)
        if r and d and SequenceMatcher(None, r, d).ratio() >= 0.96 and compare._numbers(r) == compare._numbers(d):
            return "Resolved on re-read: both documents read the same at higher resolution."
        return ""
    # missing / added: is the text actually present in the other document near that spot?
    if f.kind == "added" and len(target_d) >= 6:
        hay, needle = _read_loc(ref, f.ref_loc, f.lang, grow=2), target_d
    elif f.kind == "missing" and len(target_r) >= 6:
        hay, needle = _read_loc(des, f.des_loc, f.lang, grow=2), target_r
    else:
        return ""
    m = SequenceMatcher(None, hay, needle, autojunk=False)
    covered = sum(b.size for b in m.get_matching_blocks())
    if covered / len(needle) >= 0.92:
        return "Resolved on re-read: the text is present in the other document at this position."
    return ""


def _locate(regions, quote: str) -> list:
    """Find the line that best matches an AI quote so it gets a screenshot too."""
    from difflib import SequenceMatcher
    if not quote:
        return []
    q = quote.lower()[:120]
    best, loc = 0.0, []
    for r in regions:
        for ln in r.lines:
            s = SequenceMatcher(None, q, ln.text.lower()).ratio()
            if s > best:
                best, loc = s, [(r.page, [int(v) for v in ln.box])]
    return loc if best > 0.5 else []
