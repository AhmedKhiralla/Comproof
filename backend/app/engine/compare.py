"""Step 2 — full-document content comparison (Approved vs Design).

Deterministic and complete: every word of both documents goes through one alignment,
so nothing can be silently skipped. AI is only used later to adjudicate each finding.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

AR_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
AR_DIACRITICS = re.compile(r"[ً-ٰٟـ]")      # harakat + tatweel
PUNCT_EDGE = re.compile(r"^[^\w؀-ۿ]+|[^\w؀-ۿ%]+$")

LANG_LABELS = {"eng": "English", "fra": "French", "ara": "Arabic"}

CRITICAL_TERMS = [
    "mg", "dose", "daily", "week", "maximum", "contraindicat", "pregnan", "breast", "child",
    "paediatric", "overdose", "do not", "must not", "not recommended", "store", "°c", "temperature",
    "مجم", "جرعة", "الجرعة", "يومي", "أسبوع", "الحمل", "الأطفال", "لا ", "درجة",
    "posologie", "par jour", "quotidien", "semaine", "maximale", "contre-indiqu", "grossesse", "allaite",
    "enfant", "surdosage", "ne pas", "ne prenez", "ne doit pas", "déconseillé", "conserver", "température",
]


@dataclass
class Token:
    raw: str
    norm: str
    page: int
    box: list
    conf: float
    line_box: list
    section: str = ""
    col: int = 0
    ncols: int = 1


@dataclass
class Finding:
    id: str
    step: int                     # 1 master audit, 2 content diff, 3 typography
    lang: str
    kind: str                     # missing / added / changed / numeric / spacing / punctuation / ...
    severity: str                 # critical / major / minor / info
    title: str
    ref_text: str = ""
    des_text: str = ""
    ref_loc: list = field(default_factory=list)   # [(page, box)]
    des_loc: list = field(default_factory=list)
    ocr_similarity: float = 0.0
    needs_ai: bool = True
    ai: dict | None = None
    note: str = ""
    # --- detail for the report
    section: str = ""
    category: str = ""
    segments: list = field(default_factory=list)       # [["eq"|"del"|"ins", text], ...]
    context_before: str = ""
    context_after: str = ""
    ref_hl: list = field(default_factory=list)          # word-level boxes [(page, box)]
    des_hl: list = field(default_factory=list)
    des_anchor: list = field(default_factory=list)      # where missing text should be [(page, box)]
    ref_anchor: list = field(default_factory=list)
    where_ref: str = ""
    where_des: str = ""
    explanation: str = ""
    action: str = ""
    ref_crop: list = field(default_factory=list)        # [page, x0, y0, x1, y1] of the screenshot
    des_crop: list = field(default_factory=list)
    read_conf: int = 100          # mean reading confidence of the words involved (OCR 0-100; text layer 100)
    data: dict = field(default_factory=dict)   # structured values for checks beyond the text (colour, barcodes...)


# ---------------------------------------------------------------- normalisation

BIDI = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


AR_NUM_RUN = re.compile(r"[٠-٩۰-۹][٠-٩۰-۹٫,.]*[٠-٩۰-۹]|[٠-٩۰-۹]")


def fix_ar_digits(w: str) -> str:
    """Tesseract emits Arabic-Indic numbers in visual (reversed) order: ٠١ for ١٠ (10)."""
    return AR_NUM_RUN.sub(lambda m: m.group(0)[::-1], w)


def norm_word(w: str, lang: str) -> list[str]:
    w = BIDI.sub("", w)
    if lang == "ara":
        w = fix_ar_digits(w)
    w = unicodedata.normalize("NFKC", w).translate(AR_INDIC)
    # typographic apostrophes and French ligatures: OCR and text layers disagree on these glyphs
    w = w.replace("’", "'").replace("‘", "'").replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    w = re.sub(r"(?<=\d)[,٫](?=\d)", ".", w)          # Arabic decimal comma -> point
    w = w.lower()
    if lang == "ara":
        w = AR_DIACRITICS.sub("", w)
        w = re.sub("[أإآٱ]", "ا", w).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    w = PUNCT_EDGE.sub("", w)
    if not w:
        return []
    # split numbers from units so "2.5mg" == "2.5 mg"
    parts = re.findall(r"\d+(?:\.\d+)?|%|[^\d%]+", w)
    out = []
    for p in parts:
        p = PUNCT_EDGE.sub("", p)
        if p:
            out.append(p)
    return out


SMPC = {
    "1": "1. Name of the medicinal product", "2": "2. Qualitative and quantitative composition",
    "3": "3. Pharmaceutical form", "4": "4. Clinical particulars", "4.1": "4.1 Therapeutic indications",
    "4.2": "4.2 Posology and method of administration", "4.3": "4.3 Contraindications",
    "4.4": "4.4 Special warnings and precautions", "4.5": "4.5 Interactions",
    "4.6": "4.6 Fertility, pregnancy and lactation", "4.7": "4.7 Driving and using machines",
    "4.8": "4.8 Undesirable effects", "4.9": "4.9 Overdose", "5": "5. Pharmacological properties",
    "5.1": "5.1 Pharmacodynamic properties", "5.2": "5.2 Pharmacokinetic properties",
    "5.3": "5.3 Preclinical safety data", "6": "6. Pharmaceutical particulars", "6.1": "6.1 List of excipients",
    "6.2": "6.2 Incompatibilities", "6.3": "6.3 Shelf life", "6.4": "6.4 Storage precautions",
    "6.5": "6.5 Container", "6.6": "6.6 Disposal and handling", "7": "7. Licence holder and manufacturer",
}
SMPC_FR = {
    "1": "1. Dénomination du médicament", "2": "2. Composition qualitative et quantitative",
    "3": "3. Forme pharmaceutique", "4": "4. Données cliniques", "4.1": "4.1 Indications thérapeutiques",
    "4.2": "4.2 Posologie et mode d'administration", "4.3": "4.3 Contre-indications",
    "4.4": "4.4 Mises en garde et précautions d'emploi", "4.5": "4.5 Interactions",
    "4.6": "4.6 Fertilité, grossesse et allaitement", "4.7": "4.7 Conduite et utilisation de machines",
    "4.8": "4.8 Effets indésirables", "4.9": "4.9 Surdosage", "5": "5. Propriétés pharmacologiques",
    "5.1": "5.1 Propriétés pharmacodynamiques", "5.2": "5.2 Propriétés pharmacocinétiques",
    "5.3": "5.3 Données de sécurité préclinique", "6": "6. Données pharmaceutiques",
    "6.1": "6.1 Liste des excipients", "6.2": "6.2 Incompatibilités", "6.3": "6.3 Durée de conservation",
    "6.4": "6.4 Précautions de conservation", "6.5": "6.5 Nature et contenu de l'emballage",
    "6.6": "6.6 Précautions d'élimination et manipulation", "7": "7. Titulaire de l'autorisation",
}
PIL_EN = [
    ("used for", "PIL 1 · What the medicine is and what it is used for"),
    ("before you take", "PIL 2 · What you need to know before you take"),
    ("need to know", "PIL 2 · What you need to know before you take"),
    ("do not take", "PIL 2 · Do not take"), ("warnings", "PIL 2 · Warnings and precautions"),
    ("other medicines", "PIL 2 · Other medicines"), ("pregnan", "PIL 2 · Pregnancy and breast-feeding"),
    ("driving", "PIL 2 · Driving and using machines"), ("how to take", "PIL 3 · How to take"),
    ("instructions for", "PIL 3 · Instructions for use"), ("if you take more", "PIL 3 · Overdose"),
    ("if you forget", "PIL 3 · If you forget a dose"), ("if you stop", "PIL 3 · If you stop taking"),
    ("side effects", "PIL 4 · Possible side effects"), ("how to store", "PIL 5 · Storage"),
    ("contents of the pack", "PIL 6 · Contents of the pack"), ("marketing authorisation", "PIL 6 · Licence holder and manufacturer"),
]
PIL_FR = [
    ("qu'est-ce que", "PIL 1 · Qu'est-ce que le médicament et dans quels cas est-il utilisé"),
    ("informations à connaître", "PIL 2 · Informations à connaître avant de prendre"),
    ("ne prenez jamais", "PIL 2 · Ne prenez jamais"), ("avertissements", "PIL 2 · Avertissements et précautions"),
    ("autres médicaments", "PIL 2 · Autres médicaments"), ("grossesse", "PIL 2 · Grossesse et allaitement"),
    ("conduite de véhicules", "PIL 2 · Conduite et utilisation de machines"),
    ("comment prendre", "PIL 3 · Comment prendre"), ("mode d'emploi", "PIL 3 · Mode d'emploi"),
    ("si vous avez pris plus", "PIL 3 · Surdosage"), ("si vous oubliez", "PIL 3 · Oubli d'une dose"),
    ("si vous arrêtez", "PIL 3 · Arrêt du traitement"),
    ("effets indésirables", "PIL 4 · Effets indésirables éventuels"),
    ("comment conserver", "PIL 5 · Conservation"), ("contenu de l'emballage", "PIL 6 · Contenu de l'emballage"),
    ("titulaire", "PIL 6 · Titulaire et fabricant"),
]
PIL_AR = [
    ("ما هو", "PIL 1 · ما هو الدواء وما هو يستخدم له"), ("ما تحتاج", "PIL 2 · ما تحتاج معرفته قبل التناول"),
    ("لا يؤخذ", "PIL 2 · لا يؤخذ"), ("تحذيرات", "PIL 2 · التحذيرات والاحتياطات"),
    ("الأدوية الأخرى", "PIL 2 · الأدوية الأخرى"), ("الحمل", "PIL 2 · الحمل والرضاعة"),
    ("القيادة", "PIL 2 · القيادة واستخدام الآلات"), ("كيفية تناول", "PIL 3 · كيفية التناول"),
    ("تعليمات حول", "PIL 3 · تعليمات الاستخدام"), ("الجرعة الزائدة", "PIL 3 · الجرعة الزائدة"),
    ("إذا نسيت", "PIL 3 · نسيان الجرعة"), ("إذا توقفت", "PIL 3 · التوقف عن التناول"),
    ("الآثار الجانبية", "PIL 4 · الآثار الجانبية"), ("كيفية تخزين", "PIL 5 · التخزين"),
    ("محتويات العبوة", "PIL 6 · محتويات العبوة"), ("صاحب الترخيص", "PIL 6 · صاحب الترخيص والمصنع"),
]
HEAD_EN = re.compile(r"^\s*(\d(?:\.\d)?)\s*\.?\s*([A-ZÀ-Þ][A-Za-zà-ÿÀ-ÞœŒ&,'’\- ]{3,})")


def heading_of(text: str, lang: str) -> str | None:
    t = BIDI.sub("", text).strip()
    if len(t) > 75:
        return None
    if lang in ("eng", "fra"):
        low = t.lower().replace("’", "'")
        for key, name in (PIL_FR if lang == "fra" else PIL_EN):
            if key in low[:55] and len(t.split()) <= 14:
                return name
        m = HEAD_EN.match(t)
        if m and m.group(1) in SMPC:
            return (SMPC_FR if lang == "fra" else SMPC)[m.group(1)]
        return None
    for key, name in PIL_AR:
        if key in t[:40] and len(t.split()) <= 9:
            return name
    return None


def tokens_from_regions(regions, lang: str, order: str = "ltr") -> list[Token]:
    regs = [r for r in regions if r.lang == lang]
    # Regions are grouped per page; within a page, columns read LTR or RTL.
    pages = sorted({r.page for r in regs})
    toks: list[Token] = []
    section = ""
    bullet = {"٠", "ه", "0", "o", "•", "ء", "»", "«", "e", "-"}
    for p in pages:
        rp = sorted([r for r in regs if r.page == p], key=lambda r: r.box[0], reverse=(order == "rtl"))
        allp = sorted([r for r in regions if r.page == p], key=lambda r: r.box[0])
        for r in rp:
            col = allp.index(r) + 1
            for ln in r.lines:
                h = heading_of(ln.text, lang)
                if h:
                    section = h
                prev = None
                for wi, w in enumerate(ln.words):
                    if prev is not None and w.text == prev.text and _overlap(w.box, prev.box) > 0.3:
                        continue                      # OCR duplicated the same word
                    prev = w
                    if BIDI.sub("", w.text).strip() in bullet and (wi == 0 or lang == "ara"):
                        continue                      # bullet glyphs read as letters/digits
                    for n in norm_word(w.text, lang):
                        toks.append(Token(w.text, n, p, w.box, w.conf, ln.box, section, col, len(allp)))
    return toks


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return inter / area


def tokens_from_text(text: str, lang: str) -> list[Token]:
    toks = []
    for line in text.splitlines():
        for w in line.split():
            for n in norm_word(w, lang):
                toks.append(Token(w, n, -1, [0, 0, 0, 0], 100.0, [0, 0, 0, 0]))
    return toks


def is_arabic(s: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in s)


# ---------------------------------------------------------------- alignment

def _ratio(a: list[Token], b: list[Token]) -> float:
    sm = SequenceMatcher(None, [t.norm for t in a], [t.norm for t in b], autojunk=False)
    return sm.ratio()


def best_order(ref_regions, des_regions, lang: str):
    """Scanned pages read LTR page-by-page; artwork columns may run RTL for Arabic.
    Pick the reading order of each side that aligns best."""
    best = None
    for ro in ("ltr", "rtl"):
        for do in ("ltr", "rtl"):
            a = tokens_from_regions(ref_regions, lang, ro)
            b = tokens_from_regions(des_regions, lang, do)
            if not a or not b:
                continue
            r = _ratio(a, b)
            if best is None or r > best[0]:
                best = (r, a, b, ro, do)
    return best


CONFUSABLE = str.maketrans({"l": "1", "i": "1", "|": "1", "s": "5", "o": "0", "b": "8", "z": "2", "g": "9"})


def _confusable(s: str) -> str:
    return re.sub(r"[^\w\u0600-\u06ff]", "", s.lower()).translate(CONFUSABLE)


SIG_NUM = re.compile(r"(\d+(?:[.,]\d+)?\s*/\s*\d+(?:[.,]\d+)*"          # fractions 1/10,000
                     r"|\d+[.,]\d+"                                     # decimals 2.5
                     r"|\d{2,}"                                          # multi-digit 10, 30
                     r"|\d+(?=\s*(?:mg|g\b|ml|%|°|µg|mcg|week|day|hour|h\b|time|year|month|"
                     r"مجم|ملغ|جم|مل|اسبوع|أسبوع|يوم|ساع|مرة|سنة|شهر|درج)))", re.I)


def _numbers(s: str) -> list[str]:
    """Clinically meaningful numbers only — stray single digits from OCR specks are ignored."""
    s = fix_ar_digits(BIDI.sub("", unicodedata.normalize("NFKC", s))).translate(AR_INDIC).replace("٫", ".")
    # A comma followed by one or two digits is a decimal comma (Arabic leaflets print ١,٢٥ for 1.25);
    # a comma before three digits stays a thousands separator (10,000).
    s = re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", s)
    return sorted(re.sub(r"\s|,", "", m).replace("٫", ".") for m in SIG_NUM.findall(s))


DOSAGE_FORMS = [
    "tablet", "film-coated", "film", "capsule", "syrup", "suspension", "solution", "injection", "infusion", "cream",
    "ointment", "gel", "sachet", "granule", "powder", "drops", "spray", "patch", "suppositor", "orodispersible",
    "oro-dispersible", "dispersible", "effervescent", "chewable", "dissolvable", "dissolving", "extended-release",
    "prolonged-release", "modified-release", "gastro-resistant", "lozenge", "inhaler",
    "اقراص", "قرص", "فيلم", "افلام", "كبسول", "شراب", "معلق", "محلول", "حقن", "كريم", "مرهم", "جل", "اكياس",
    "حبيبات", "بودره", "نقط", "بخاخ", "لصقه", "فوار", "للمضغ", "سريعه الذوبان", "للذوبان", "تحاميل",
]


def _ar_fold(s: str) -> str:
    s = AR_DIACRITICS.sub("", BIDI.sub("", s.lower()))
    return re.sub("[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه")


def dosage_terms(s: str) -> set[str]:
    t = _ar_fold(s)
    return {f for f in DOSAGE_FORMS if f in t}


LOW_READ_CONF = 75


def _severity(kind: str, ref_txt: str, des_txt: str, n_tokens: int, sim: float, lang: str = "eng") -> str:
    low = f" {ref_txt} {des_txt} ".lower()
    if dosage_terms(ref_txt) != dosage_terms(des_txt):
        return "major"           # dosage-form wording changed (film / tablet / oro-dispersible ...)
    if _numbers(ref_txt) != _numbers(des_txt):
        # Arabic-Indic digits OCR poorly: when the words around them match, verify rather than alarm
        if lang == "ara" and sim >= 0.5:
            return "major"
        return "critical"
    if any(t in low for t in CRITICAL_TERMS) and sim < 0.8:
        return "critical" if kind in ("missing", "added") else "major"
    if n_tokens >= 4 and sim < 0.6:
        return "major"
    if sim >= 0.75:
        return "info"            # very likely OCR noise — AI decides
    return "minor"


def _display(tokens: list[Token]) -> str:
    """Original words (one per OCR word, even when split into several tokens)."""
    out, last = [], None
    for t in tokens:
        if t.box is last:
            continue
        last = t.box
        out.append(fix_ar_digits(BIDI.sub("", t.raw)))   # show Arabic-Indic numbers in reading order
    return " ".join(out)


def _loc(tokens: list[Token]) -> list:
    """Group token line-boxes by page into one rectangle per page."""
    by_page: dict = {}
    for t in tokens:
        b = by_page.setdefault(t.page, list(t.line_box))
        b[0], b[1] = min(b[0], t.line_box[0]), min(b[1], t.line_box[1])
        b[2], b[3] = max(b[2], t.line_box[2]), max(b[3], t.line_box[3])
    return [(p, [int(v) for v in b]) for p, b in by_page.items()]


def _word_loc(tokens: list[Token]) -> list:
    return [(t.page, [int(v) for v in t.box]) for t in tokens]


CATEGORIES = [
    ("Strength & composition", ["composition", "excipient", "name of the medicinal", "pharmaceutical form",
                                "dénomination", "forme pharmaceutique", "qu'est-ce que",
                                "محتويات", "ما هو"], ["contains", "fumarate", "mg of", "contient", "يحتوي", "المادة الفعالة"]),
    ("Dose & administration", ["posology", "posologie", "comment prendre", "mode d'emploi", "mode d'administration",
                               "oubli", "arrêt", "كيفية", "تعليمات", "نسيت", "توقفت"],
     ["dose", "daily", "week", "titration", "tongue", "swallow", "water", "par jour", "semaine", "avaler",
      "جرعة", "يوميا", "أسبوع", "اللسان"]),
    ("Safety information", ["contraindication", "warning", "interaction", "pregnan", "driving", "undesirable",
                            "overdose", "contre-indication", "mises en garde", "avertissement", "grossesse",
                            "conduite", "effets indésirables", "surdosage", "ne prenez jamais",
                            "لا يؤخذ", "تحذير", "الأدوية الأخرى", "الحمل", "القيادة", "الآثار",
                            "الجرعة الزائدة"], ["contraindicat", "must not", "risk", "caution", "contre-indiqu",
                                                "ne doit pas", "risque", "لا تتناول"]),
    ("Pharmacology", ["pharmacodynamic", "pharmacokinetic", "preclinical", "pharmacodynamique",
                      "pharmacocinétique", "préclinique"], ["half-life", "clearance", "demi-vie"]),
    ("Storage, pack & manufacturer", ["storage", "shelf", "container", "disposal", "licence", "conservation",
                                      "emballage", "titulaire", "التخزين",
                                      "صاحب الترخيص"], ["°c", "store", "conserver", "درجة", "يحفظ", "يخزن"]),
]


def category_of(section: str, text: str) -> str:
    s, t = section.lower(), text.lower()
    for name, sec_keys, txt_keys in CATEGORIES:
        if any(k in s for k in sec_keys):
            return name
    for name, _, txt_keys in CATEGORIES:
        if any(k in t for k in txt_keys):
            return name
    return "General text"


def where(tokens: list[Token], doc_label: str) -> str:
    if not tokens:
        return ""
    t = tokens[0]
    if t.page < 0:
        return "approved text"
    if t.ncols >= 3:
        return f"page {t.page + 1}, column {t.col} of {t.ncols}"
    if t.ncols == 2:
        return f"scan page {t.page + 1}, {'left' if t.col == 1 else 'right'} half"
    return f"page {t.page + 1}"


ACTIONS = {
    "numeric": "Correct the value on the artwork to match the approved leaflet, or raise a change control "
               "if the approved text itself is wrong. Numbers must never differ.",
    "missing": "Restore the missing text on the artwork exactly as approved.",
    "added": "Remove the extra text, or get it approved through change control before printing.",
    "changed": "Align the wording on the artwork with the approved leaflet.",
}
IMPACT = {
    "Strength & composition": "Wrong strength or composition is a product-identity error and a recall risk.",
    "Dose & administration": "Dosing and administration text directly guides how patients take the medicine.",
    "Safety information": "Safety text protects patients; any change needs regulatory approval.",
    "Pharmacology": "Scientific data must match the approved SmPC.",
    "Storage, pack & manufacturer": "Storage and pack details affect product quality and traceability.",
    "General text": "Approved wording must be reproduced exactly on the printed leaflet.",
}


def _words(tokens: list[Token]) -> list[tuple]:
    """Collapse tokens back to OCR words: (raw, norm-joined, token list)."""
    out = []
    for t in tokens:
        if out and out[-1][2][-1].box is t.box:
            out[-1] = (out[-1][0], out[-1][1] + t.norm, out[-1][2] + [t])
        else:
            out.append((BIDI.sub("", t.raw), t.norm, [t]))
    return out


def build_detail(f: "Finding", ref_tokens, des_tokens, i1, i2, j1, j2):
    rt, dt = ref_tokens[i1:i2], des_tokens[j1:j2]
    rw, dw = _words(rt), _words(dt)
    sm = SequenceMatcher(None, [w[1] for w in rw], [w[1] for w in dw], autojunk=False)
    segs, r_hl, d_hl = [], [], []
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            segs.append(["eq", " ".join(w[0] for w in rw[a1:a2])])
            continue
        if a2 > a1:
            segs.append(["del", " ".join(w[0] for w in rw[a1:a2])])
            r_hl += [(w[2][0].page, [int(v) for v in w[2][0].box]) for w in rw[a1:a2]]
        if b2 > b1:
            segs.append(["ins", " ".join(w[0] for w in dw[b1:b2])])
            d_hl += [(w[2][0].page, [int(v) for v in w[2][0].box]) for w in dw[b1:b2]]
    side = ref_tokens if rt or not dt else des_tokens
    lo, hi = (i1, i2) if side is ref_tokens else (j1, j2)
    f.context_before = " ".join(w[0] for w in _words(side[max(0, lo - 12):lo])[-6:])
    f.context_after = " ".join(w[0] for w in _words(side[hi:hi + 12])[:6])
    f.segments, f.ref_hl, f.des_hl = segs, r_hl, d_hl
    if not dt and j1 > 0:
        t = des_tokens[min(j1, len(des_tokens)) - 1]
        f.des_anchor = [(t.page, [int(v) for v in t.box])]
    if not rt and i1 > 0:
        t = ref_tokens[min(i1, len(ref_tokens)) - 1]
        f.ref_anchor = [(t.page, [int(v) for v in t.box])]
    sec_src = rt or (ref_tokens[i1 - 1:i1] if i1 else []) or dt
    f.section = sec_src[0].section if sec_src else ""
    if not f.section and dt:
        f.section = dt[0].section
    f.category = category_of(f.section, f.ref_text + " " + f.des_text)
    f.where_ref = where(rt or ref_tokens[max(0, i1 - 1):i1], "approved")
    f.where_des = where(dt or des_tokens[max(0, j1 - 1):j1], "design")
    removed = " ".join(x[1] for x in segs if x[0] == "del")
    added = " ".join(x[1] for x in segs if x[0] == "ins")
    q = lambda x: f"“{x[:160]}{'…' if len(x) > 160 else ''}”"
    if f.kind == "missing":
        f.explanation = f"The approved leaflet has {q(removed or f.ref_text)} here; the design leaves it out."
    elif f.kind == "added":
        f.explanation = f"The design adds {q(added or f.des_text)}, which is not in the approved leaflet."
    elif f.kind == "numeric":
        rn, dn = _numbers(f.ref_text), _numbers(f.des_text)
        f.explanation = (f"Approved reads {q(removed or f.ref_text)}, design reads {q(added or f.des_text)}. "
                         f"Numbers: approved {', '.join(rn) or 'none'} → design {', '.join(dn) or 'none'}.")
    elif f.kind == "ocr":
        f.explanation = "The two readings differ only by look-alike characters (l/1, O/0, S/5); most likely the same text."
    else:
        f.explanation = f"Approved reads {q(removed or f.ref_text)}; the design reads {q(added or f.des_text)}."
    f.action = ACTIONS.get(f.kind, "Check against the approved leaflet.")
    if f.kind != "ocr":
        f.explanation += " " + IMPACT.get(f.category, "")


def diff(ref_tokens: list[Token], des_tokens: list[Token], lang: str, start_id: int = 1,
         merge_gap: int = 2) -> tuple[list[Finding], list[Finding]]:
    """Returns (content findings, spacing findings). Spacing = same characters, different word breaks."""
    a = [t.norm for t in ref_tokens]
    b = [t.norm for t in des_tokens]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    ops = [o for o in sm.get_opcodes()]
    # merge non-equal ops separated by small equal runs
    groups, cur = [], None
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if cur and (i2 - i1) <= merge_gap and (j2 - j1) <= merge_gap:
                cur["pending"].append((i1, i2, j1, j2))
            elif cur:
                groups.append(cur)
                cur = None
            continue
        if cur is None:
            cur = {"i1": i1, "i2": i2, "j1": j1, "j2": j2, "pending": []}
        else:
            cur["i2"], cur["j2"] = i2, j2
            cur["pending"] = []
        cur["i2"], cur["j2"] = max(cur["i2"], i2), max(cur["j2"], j2)
    if cur:
        groups.append(cur)

    findings, spacing = [], []
    n = start_id
    for g in groups:
        rt, dt = ref_tokens[g["i1"]:g["i2"]], des_tokens[g["j1"]:g["j2"]]
        r_txt, d_txt = _display(rt), _display(dt)
        r_join = "".join(t.norm for t in rt)
        d_join = "".join(t.norm for t in dt)
        if r_join == d_join:
            sf = Finding(f"S{n}", 3, lang, "spacing", "minor", "Word spacing differs",
                         r_txt, d_txt, _loc(rt), _loc(dt), 1.0, True)
            build_detail(sf, ref_tokens, des_tokens, g["i1"], g["i2"], g["j1"], g["j2"])
            sf.explanation = f"Same letters, different word breaks: approved “{r_txt}”, design “{d_txt}”."
            sf.action = "Fix the spacing on the artwork if the OCR reading is confirmed."
            spacing.append(sf)
            n += 1
            continue
        sim = SequenceMatcher(None, r_join, d_join).ratio() if (r_join and d_join) else 0.0
        if r_join and d_join and _confusable(r_join) == _confusable(d_join):
            r_punct, d_punct = re.sub(r"[\w\s]", "", r_txt), re.sub(r"[\w\s]", "", d_txt)
            r_words, d_words = len(r_txt.split()), len(d_txt.split())
            if r_punct != d_punct or r_words != d_words:
                # Letters read almost alike (OCR), but punctuation or word breaks really differ: Step 3.
                kind = "spacing" if r_words != d_words else "punctuation"
                tf = Finding(f"S{n}", 3, lang, kind, "minor",
                             "Word spacing differs" if kind == "spacing" else "Punctuation differs",
                             r_txt, d_txt, _loc(rt), _loc(dt), 1.0, True)
                build_detail(tf, ref_tokens, des_tokens, g["i1"], g["i2"], g["j1"], g["j2"])
                tf.explanation = (f"Approved “{r_txt}”, design “{d_txt}”. The letters read almost the same, "
                                  f"but the {'word breaks' if kind == 'spacing' else 'punctuation'} differ.")
                tf.action = "Match the approved spacing and punctuation."
                tf.category = "Typography"
                spacing.append(tf)
            else:
                of = Finding(f"C{n}", 2, lang, "ocr", "info", "Probable OCR misread (look-alike characters)",
                             r_txt, d_txt, _loc(rt), _loc(dt), 1.0, True)
                build_detail(of, ref_tokens, des_tokens, g["i1"], g["i2"], g["j1"], g["j2"])
                findings.append(of)
            n += 1
            continue
        if not dt:
            kind, title = "missing", "Text in approved leaflet is missing from design"
            anchor = des_tokens[max(0, g["j1"] - 3):g["j1"] + 3]
            d_loc = _loc(anchor)
        elif not rt:
            kind, title = "added", "Text in design is not in approved leaflet"
            anchor = ref_tokens[max(0, g["i1"] - 3):g["i1"] + 3]
            r_loc = _loc(anchor)
        else:
            kind, title = "changed", "Text differs"
        if _numbers(r_txt) != _numbers(d_txt):
            kind, title = "numeric", "Numbers differ (dose / strength / value)"
        sev = _severity(kind, r_txt, d_txt, max(len(rt), len(dt)), sim, lang)
        confs = [t.conf for t in (rt + dt)]
        read_conf = int(round(sum(confs) / len(confs))) if confs else 100
        if sev == "critical" and read_conf < LOW_READ_CONF:
            # A garbled reading must not raise a critical alarm on its own: hold it as major until a person
            # (or the AI review) confirms what the print actually says.
            sev = "major"
        f = Finding(f"C{n}", 2, lang, kind, sev, title, r_txt, d_txt,
                    _loc(rt) if rt else r_loc, _loc(dt) if dt else d_loc, round(sim, 2))
        f.read_conf = read_conf
        build_detail(f, ref_tokens, des_tokens, g["i1"], g["i2"], g["j1"], g["j2"])
        f.title = _title(f)
        findings.append(f)
        n += 1
    return findings, spacing


def _title(f: "Finding") -> str:
    where = re.sub(r"^(PIL \d+ · |\d+(\.\d+)?\.?\s+)", "", f.section) if f.section else ""
    base = {"missing": "Missing from design", "added": "Added in design", "numeric": "Number changed",
            "changed": "Wording changed"}.get(f.kind, f.title)
    return f"{base} — {where}" if where else base


def typography(ref_tokens: list[Token], des_tokens: list[Token], lang: str, start_id: int = 1) -> list[Finding]:
    """Step 3 — on words whose content matches, compare punctuation, capitalisation and digit style.
    Only high-confidence OCR words are used to keep noise out."""
    a = [t.norm for t in ref_tokens]
    b = [t.norm for t in des_tokens]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out, n = [], start_id
    seen = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            continue
        # Word breaks inside matching text: "2.5mg" vs "2.5 mg", "beta1-selective" vs "beta -1 selective".
        for k in range(i2 - i1 - 1):
            r1, r2, d1, d2 = ref_tokens[i1 + k], ref_tokens[i1 + k + 1], des_tokens[j1 + k], des_tokens[j1 + k + 1]
            jr, jd = r1.box is r2.box, d1.box is d2.box
            exact = min(r1.conf, r2.conf, d1.conf, d2.conf) >= 99
            if jr == jd or min(r1.conf, r2.conf, d1.conf, d2.conf) < 88 or (lang == "ara" and not exact):
                continue
            rw = BIDI.sub("", r1.raw if jr else f"{r1.raw} {r2.raw}")
            dw = BIDI.sub("", d1.raw if jd else f"{d1.raw} {d2.raw}")
            if (rw, dw) in seen:
                continue
            seen.add((rw, dw))
            sf = Finding(f"T{n}", 3, lang, "spacing", "minor", "Word spacing differs", rw, dw,
                         [(r1.page, [int(v) for v in r1.line_box])], [(d1.page, [int(v) for v in d1.line_box])],
                         1.0, True)
            sf.ref_hl = [(r1.page, [int(v) for v in r1.box])] + ([] if jr else [(r2.page, [int(v) for v in r2.box])])
            sf.des_hl = [(d1.page, [int(v) for v in d1.box])] + ([] if jd else [(d2.page, [int(v) for v in d2.box])])
            sf.segments = [["del", rw], ["ins", dw]]
            sf.section, sf.category = r1.section, "Typography"
            sf.where_ref, sf.where_des = where([r1], ""), where([d1], "")
            sf.context_before = " ".join(BIDI.sub("", t.raw) for t in ref_tokens[max(0, i1 + k - 5):i1 + k])
            sf.context_after = " ".join(BIDI.sub("", t.raw) for t in ref_tokens[i1 + k + 2:i1 + k + 7])
            sf.explanation = f"Same text, different spacing: approved “{rw}”, design “{dw}”."
            sf.action = "Match the approved spacing (for example between a number and its unit)."
            out.append(sf)
            n += 1
        for k in range(i2 - i1):
            r, d = ref_tokens[i1 + k], des_tokens[j1 + k]
            if r.raw == d.raw or (r.raw, d.raw) in seen:
                continue
            if min(r.conf, d.conf) < 88:
                continue
            exact = min(r.conf, d.conf) >= 99      # text layer or AI reading: dots and commas are reliable
            kind = None
            r_digits_ar = bool(re.search("[٠-٩]", r.raw))
            d_digits_ar = bool(re.search("[٠-٩]", d.raw))
            if r_digits_ar != d_digits_ar:
                kind, title = "digits", "Digit style differs (Western vs Arabic-Indic)"
            elif r.raw.strip("().,;:-") == d.raw.strip("().,;:-") and r.raw != d.raw:
                rp, dp = re.sub(r"[\w]", "", r.raw), re.sub(r"[\w]", "", d.raw)
                if exact or set(rp) - set(".,") or set(dp) - set(".,"):
                    kind, title = "punctuation", "Punctuation differs"
            elif lang != "ara" and r.raw.lower() == d.raw.lower():
                kind, title = "case", "Capitalisation differs"
            if not kind:
                continue
            # keep the reference token's position for the screenshot
            if r.raw.translate(AR_INDIC).replace("٫", ".").replace(",", ".") == d.raw.translate(AR_INDIC).replace("٫", ".").replace(",", ".") and kind != "digits":
                continue
            seen.add((r.raw, d.raw))
            tf = Finding(f"T{n}", 3, lang, kind, "minor", title, r.raw, d.raw,
                         [(r.page, [int(v) for v in r.line_box])], [(d.page, [int(v) for v in d.line_box])],
                         1.0, kind != "digits")
            tf.ref_hl = [(r.page, [int(v) for v in r.box])]
            tf.des_hl = [(d.page, [int(v) for v in d.box])]
            tf.segments = [["del", BIDI.sub("", r.raw)], ["ins", BIDI.sub("", d.raw)]]
            tf.section, tf.category = r.section, "Typography"
            tf.where_ref, tf.where_des = where([r], ""), where([d], "")
            tf.context_before = " ".join(BIDI.sub("", t.raw) for t in ref_tokens[max(0, i1 + k - 5):i1 + k])
            tf.context_after = " ".join(BIDI.sub("", t.raw) for t in ref_tokens[i1 + k + 1:i1 + k + 6])
            tf.explanation = {"digits": "Same number, written in a different digit system.",
                              "punctuation": f"Punctuation differs: approved “{r.raw}”, design “{d.raw}”.",
                              "case": f"Capitalisation differs: approved “{r.raw}”, design “{d.raw}”."}[kind]
            tf.action = ("Confirm the digit style follows your house style and EDA expectations."
                         if kind == "digits" else "Match the approved punctuation and capitalisation.")
            out.append(tf)
            n += 1
    return out
