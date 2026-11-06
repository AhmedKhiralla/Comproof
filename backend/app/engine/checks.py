"""Checks beyond the text, run after the three text levels.

Level 4  Colour      ΔE2000 against the approved Standard / Light / Dark shade set, ink by ink
Level 5  Barcodes    decode, validate GTIN and GS1 data, compare with the approved artwork
Level 6  Graphics    overlay: graphic elements missing, added or changed
Level 7  Print       minimum text size, Braille, dieline (folds and cut edges)
"""
from __future__ import annotations

from PIL import Image

from . import compare

STEP_COLOUR, STEP_BARCODE, STEP_GRAPHICS, STEP_PRINT = 4, 5, 6, 7


def _finding(fid: str, step: int, kind: str, severity: str, title: str, **kw) -> compare.Finding:
    f = compare.Finding(fid, step, "eng", kind, severity, title, kw.pop("ref_text", ""), kw.pop("des_text", ""),
                        kw.pop("ref_loc", []), kw.pop("des_loc", []), 1.0, False)
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def _lab_txt(d: dict | None) -> str:
    return f"L* {d['L']:.1f}  a* {d['a']:.1f}  b* {d['b']:.1f}" if d else "—"


def colour_check(cfg: dict, measurement: dict, std_path: str | None, des_path: str, n: int, progress):
    from . import colour
    progress("Level 4: measuring colour against the shade standards")
    res = colour.check_sample(measurement, std_path, None if cfg["sample_source"] == "spectro" else des_path,
                              cfg["sample_source"], cfg["tolerance"], cfg["flat_tolerance"],
                              spectro_sample=_spectro(des_path) if cfg["sample_source"] == "spectro" else None)
    images = res.pop("_images", None) or {}
    std_img = None
    if images and std_path:
        std_img, _ = colour.load_image(std_path)
        std_img, _ = colour.calibrate(std_img, measurement.get("source", "scan"))
    findings, shots = [], {}
    for row in res["inks"]:
        v = row["verdict"]
        sev = {"fail": "major", "screen": "minor", "not_measured": "minor"}.get(v, "info")
        if v == "fail" and row.get("de_standard", 0) > 3 * cfg["tolerance"]:
            sev = "critical"
        title = f"{row['name']}: " + ({"pass": "within the shade range", "fail": "outside the shade range",
                                       "screen": "screening only (photo)", "not_measured": "not measured"}[v])
        fid = f"K{n}"
        n += 1
        expl = row.get("reason", "")
        if v == "screen":
            expl = (f"Photo screening (not a pass/fail measurement): {row.get('reason', '')} Check with a scan or a "
                    "spectrophotometer before deciding.")
        f = _finding(fid, STEP_COLOUR, "colour", sev, title,
                     ref_text=f"Standard {_lab_txt(row['standard'])}", des_text=f"Sample {_lab_txt(row.get('sample'))}",
                     section=row["name"], category="Colour", explanation=expl,
                     action=" ".join(row.get("advice") or []) or ("No action." if v == "pass" else
                                                                     "Measure the sample again or check the print."),
                     data={k: row.get(k) for k in ("id", "name", "status", "standard", "light", "dark", "sample",
                                                   "de_standard", "de_light", "de_dark", "position", "off_path",
                                                   "verdict", "where", "dL", "da", "db")})
        strip = colour.swatch_strip([("Dark", row["dark"]), ("Standard", row["standard"]), ("Light", row["light"])])
        sample_strip = colour.swatch_strip([("Sample", row.get("sample")), ("Standard", row["standard"])])
        a_img, b_img = strip, sample_strip
        box = row.get("box")
        if box and images.get("sample") is not None and std_img is not None and box[2] > box[0]:
            m = 40
            x0, y0, x1, y1 = max(0, box[0] - m), max(0, box[1] - m), box[2] + m, box[3] + m
            a_img = _stack(strip, Image.fromarray(std_img[y0:y1, x0:x1]))
            b_img = _stack(sample_strip, Image.fromarray(images["sample"][y0:y1, x0:x1]))
        shots[fid] = (a_img, b_img)
        findings.append(f)
    return findings, shots, res, n


def _stack(top: Image.Image, bottom: Image.Image, width: int = 600) -> Image.Image:
    b = bottom.copy()
    b.thumbnail((width, 420))
    t = top.copy()
    t.thumbnail((width, 200))
    out = Image.new("RGB", (max(t.width, b.width), t.height + b.height + 8), "white")
    out.paste(t, (0, 0))
    out.paste(b, (0, t.height + 8))
    return out


def _spectro(path: str) -> dict:
    from .colour import parse_spectro
    with open(path, "rb") as fh:
        return parse_spectro(fh.read())


def barcode_check(ref, des, product: dict, n: int, progress):
    from . import barcodes
    progress("Level 5: reading barcodes")
    r_codes, d_codes = barcodes.decode_document(ref), barcodes.decode_document(des)
    rows, problems = barcodes.compare_sets(r_codes, d_codes, product.get("purpose") or "proof", product.get("gtin"))
    findings = []
    for p in problems:
        row = p["row"]
        f = _finding(f"B{n}", STEP_BARCODE, "barcode", p["severity"], p["title"],
                     ref_text=row.get("approved") or "", des_text=row.get("test") or "",
                     ref_loc=[(row["ref_page"], [int(v) for v in row["ref_box"]])] if row.get("ref_box") else [],
                     des_loc=[(row["test_page"], [int(v) for v in row["test_box"]])] if row.get("test_box") else [],
                     section=row["symbology"], category="Barcodes", explanation=p["detail"],
                     action="Correct the barcode on the artwork, or confirm the change through change control.",
                     data={"symbology": row["symbology"], "status": row["status"]})
        n += 1
        findings.append(f)
    section = {"decoders": barcodes.decoders(), "approved": len(r_codes), "test": len(d_codes),
               "rows": [{k: v for k, v in r.items() if k not in ("ref_box", "test_box")} for r in rows]}
    return findings, section, n


def graphics_check(ref, des, ref_regions, des_regions, n: int, progress):
    from . import graphics
    progress("Level 6: overlaying graphics")
    diffs, notes = graphics.compare(ref, des, ref_regions, des_regions)
    findings, shots = [], {}
    for d in diffs:
        fid = f"G{n}"
        n += 1
        f = _finding(fid, STEP_GRAPHICS, f"graphic_{d['kind']}", d["severity"], d["title"],
                     ref_loc=[(d["page"], d["box"])], section=f"Page {d['page'] + 1}", category="Graphics & layout",
                     explanation=f"{d['title']} ({d['area_mm2']} mm²) at the marked position.",
                     action="Restore the approved graphic, or confirm the change through change control.",
                     data={"area_mm2": d["area_mm2"], "kind": d["kind"]})
        shots[fid] = (d["crop_ref"], d["crop_des"])
        findings.append(f)
    return findings, shots, {"differences": len(diffs), "notes": notes}, n


def print_check(des, des_regions, des_path: str, settings: dict, n: int, progress):
    from . import print_checks as pc
    checks = settings.get("checks") or {}
    findings, section = [], {}
    kind = settings.get("kind") or "leaflet"
    if checks.get("text_size"):
        progress("Level 7: measuring text size")
        small, stats = pc.text_sizes(des, des_regions, kind, settings.get("min_font_pt"))
        section["text_size"] = stats
        for s in small:
            f = _finding(f"P{n}", STEP_PRINT, "text_size", "major" if stats["measured"] == "exact" else "minor",
                         f"Text smaller than {stats['limit_pt']:g} pt", des_text=s["text"],
                         des_loc=[(s["page"], [int(v) for v in s["box"]])], section="Text size", category="Print",
                         explanation=f"{s['lines']} line(s) at about {s['pt']} pt "
                                     f"({'from the PDF' if stats['measured'] == 'exact' else 'estimated from the scan'}); "
                                     f"the minimum for this packaging type is {stats['limit_pt']:g} pt.",
                         action="Enlarge the text or confirm the size is acceptable for this market.",
                         data={"pt": s["pt"], "lines": s["lines"]})
            f.lang = s.get("lang", "eng")
            n += 1
            findings.append(f)
    if checks.get("braille"):
        progress("Level 7: reading Braille")
        product = settings.get("product") or {}
        problems, info = pc.braille_check(des, product.get("name", ""), settings.get("strengths") or [],
                                          bool(settings.get("braille_required")))
        section["braille"] = {"found": [{k: v for k, v in b.items() if k != "box"} for b in info["found"]],
                              "expected": info["expected"], "required": bool(settings.get("braille_required"))}
        for p in problems:
            f = _finding(f"P{n}", STEP_PRINT, "braille", p["severity"], p["title"],
                         des_text=" / ".join(b["text"] for b in info["found"]),
                         des_loc=[(p["page"], p["box"])] if p.get("box") else [], section="Braille", category="Print",
                         explanation=p["detail"], action="Correct the Braille, or confirm it by touch on the printed item.")
            n += 1
            findings.append(f)
    if checks.get("dieline") and des.kind == "pdf-vector" and des_path.lower().endswith(".pdf"):
        progress("Level 7: checking the dieline")
        scale = des.pages[0].source_dpi / 72 if des.pages else 300 / 72
        problems, info = pc.dieline_check(des_path, scale, float(settings.get("cut_margin_mm", 1.5)))
        section["dieline"] = info
        for p in problems:
            f = _finding(f"P{n}", STEP_PRINT, "dieline", p["severity"], p["title"],
                         des_loc=[(p["page"], [int(v) for v in p["box"]])], section="Dieline", category="Print",
                         explanation=p["detail"], action="Move the text away from the fold or cut edge.")
            n += 1
            findings.append(f)
    return findings, section, n
