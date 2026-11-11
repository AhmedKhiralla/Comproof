"""Step 1 — scientific / internal-consistency audit of the approved master leaflet.

Deterministic rules catch the common, checkable errors. The AI layer (ai.py) adds a
pharmacist-style review of the full text on top. Each rule returns Findings with locations
so the reviewer sees the exact spot in the scan.
"""
from __future__ import annotations

import re
from collections import Counter

from .compare import Finding

DOSAGE_FORMS = {
    "film": ["film", "strip"],
    "tablet": ["tablet", "tablets", "comprimé", "comprimés"],
    "capsule": ["capsule", "capsules", "gélule", "gélules"],
    "syrup": ["syrup", "sirop"],
    "suspension": ["suspension"],
    "injection": ["injection", "vial", "ampoule", "injectable", "flacon"],
}

SMPC_SECTIONS = ["1", "2", "3", "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9",
                 "5.1", "5.2", "5.3", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "7"]


def _lines(regions, langs=("eng", "fra")):
    for r in regions:
        if r.lang not in langs:
            continue
        for ln in r.lines:
            yield r.page, ln


def run(ref_regions, start_id: int = 1, known_strengths: list[str] | None = None) -> list[Finding]:
    lines = list(_lines(ref_regions))
    out: list[Finding] = []
    n = start_id

    def add(kind, sev, title, text, loc, note="", key="", params=None):
        nonlocal n
        f = Finding(f"M{n}", 1, "eng", kind, sev, title, text, "", loc, [], 1.0, True, None, note)
        f.key, f.params = key, params or {}
        out.append(f)
        n += 1

    text_all = "\n".join(ln.text for _, ln in lines)

    # Strengths printed in the title block, used to repair OCR that drops a decimal point ("25mg" for "2.5mg").
    head = " ".join(ln.text for _, ln in lines[:25])
    strengths = {x.replace(",", ".") for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*mg", head, re.I)}
    strengths |= set(known_strengths or [])          # strengths registered on the product in the library

    def fix(v: str) -> str:
        v = v.replace(",", ".")
        if v not in strengths and "." not in v and len(v) >= 2:
            for i in range(1, len(v)):
                cand = v[:i] + "." + v[i:]
                if cand in strengths:
                    return cand
        return v

    # 1. Strength stated vs. quantity in composition ("Each X 2.5mg ... contains 5 mg" /
    #    "Chaque comprimé de X 2,5 mg ... contient 5 mg")
    for p, ln in lines:
        m = (re.search(r"each\s+\S+\s+([\d.,]+)\s*mg.{0,60}?contains?\s+([\d.,]+)\s*mg", ln.text, re.I)
             or re.search(r"chaque\s+\S+(?:\s+\S+){0,3}?\s+([\d.,]+)\s*mg.{0,60}?contient\s+([\d.,]+)\s*mg",
                          ln.text, re.I))
        if m:
            a, b = fix(m.group(1)), fix(m.group(2))
            try:
                if float(a) != float(b):
                    add("consistency", "critical", "Strength in name does not match quantity in composition",
                        ln.text, [(p, ln.box)], f"Name says {a} mg, composition says {b} mg.",
                        key="mc.strength", params={"a": a, "b": b})
            except ValueError:
                pass

    # 2. Dosage-form wording inconsistent with the product's form
    title_block = " ".join(ln.text.lower() for _, ln in lines[:25])
    form = next((f for f, words in DOSAGE_FORMS.items() if any(w in title_block for w in words)), None)
    if form:
        others = {f: w for f, w in DOSAGE_FORMS.items() if f != form}
        for p, ln in lines:
            low = ln.text.lower()
            for f, words in others.items():
                for w in words:
                    if re.search(rf"\b{w}\b", low):
                        add("consistency", "major", f"Dosage form wording: '{w}' used for a {form} product",
                            ln.text, [(p, ln.box)], key="mc.form", params={"w": w, "form": form})
                        break

    # 3. Same heading repeated
    heads = [(p, ln) for p, ln in lines if len(ln.text) < 60 and ln.text[:1].isupper()
             and not ln.text.rstrip().endswith((".", ","))]
    seen: dict = {}
    for p, ln in heads:
        key = re.sub(r"\W", "", ln.text.lower())
        if len(key) < 8:
            continue
        if key in seen:
            add("structure", "minor", "Heading appears twice", ln.text, [seen[key], (p, ln.box)], key="mc.heading")
        else:
            seen[key] = (p, ln.box)

    # 4. ATC code format (letter, 2 digits, 2 letters, 2 digits)
    for p, ln in lines:
        m = re.search(r"(?:ATC\s*code|code\s*ATC)\s*[:\-]?\s*([A-Z0-9]{3,9})", ln.text, re.I)
        if m and not re.fullmatch(r"[A-Z]\d{2}[A-Z]{2}\d{2}", m.group(1).upper()):
            add("data", "major", f"ATC code '{m.group(1)}' is not a complete 7-character code",
                ln.text, [(p, ln.box)], key="mc.atc", params={"code": m.group(1)})

    # 5. SmPC section numbering present and in order
    found = []
    for p, ln in lines:
        m = re.match(r"\s*(\d(?:\.\d)?)\.?\s+[A-ZÀ-Þ]", ln.text)
        if m:
            found.append(m.group(1))
    missing = [s for s in SMPC_SECTIONS if s not in found]
    if found and missing:
        add("structure", "minor", "SmPC section headings not found (check numbering)",
            ", ".join(missing), [], "May also be an OCR miss — confirm on the scan.",
            key="mc.smpc", params={"missing": ", ".join(missing)})

    # 6. Maximum dose stated consistently
    maxes = re.findall(r"maximum (?:recommended )?(?:daily )?dose is\s*([\d.]+)\s*mg", text_all, re.I)
    maxes += [v.replace(",", ".") for v in
              re.findall(r"dose (?:quotidienne )?maximale(?: recommandée)? est de\s*([\d.,]+)\s*mg", text_all, re.I)]
    if len(set(maxes)) > 1:
        add("consistency", "critical", "Maximum dose stated with different values",
            ", ".join(sorted(set(maxes))) + " mg", [],
            key="mc.maxdose", params={"vals": ", ".join(sorted(set(maxes)))})

    # 7. Words glued together (missing space) — e.g. "isoprenalineor"
    glue = re.compile(r"\b([a-z]{5,})(or|and|of|the|with|to|in)\b")
    vocab = Counter(w.lower() for w in re.findall(r"[A-Za-z]{3,}", text_all))
    for p, ln in lines:
        for w in ln.words:
            m = glue.fullmatch(w.text.lower().strip(".,;:()"))
            if m and vocab[m.group(1)] >= 1 and vocab[w.text.lower().strip(".,;:()")] == 1 and w.conf > 80:
                add("typography", "minor", f"Missing space: '{w.text}'", ln.text, [(p, w.box)],
                    key="mc.glue", params={"w": w.text})
    return out
