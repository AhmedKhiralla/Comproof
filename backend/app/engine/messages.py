"""Finding texts and report labels in the reader's language (en / fr / ar).

The engine stores findings with canonical English text plus a message key and parameters; the
interface and the exports rebuild title, explanation and action from the key in the reader's
language, while quoted document text, numbers and positions stay exactly as in the material.
The finding catalog (FND) is generated from the frontend strings by scripts/gen_messages.py,
so the app and the exports always say findings in the same words.
"""
from __future__ import annotations

import copy
import re

from .messages_catalog import FND

LANGS = ("en", "fr", "ar")

CATEGORY_KEYS = {"Master leaflet": "master", "AI scientific review": "aiscience",
                 "Strength & composition": "strength", "Dose & administration": "dose",
                 "Safety information": "safety", "Pharmacology": "pharm",
                 "Storage, pack & manufacturer": "storage", "General text": "general", "Typography": "typo",
                 "Colour": "colour", "Barcodes": "barcodes", "Graphics & layout": "graphics", "Print": "print"}

_WHERE = (
    (re.compile(r"^approved text$"), "fnd.where.approved", ()),
    (re.compile(r"^page (\d+), column (\d+) of (\d+)$"), "fnd.where.col", ("n", "c", "k")),
    (re.compile(r"^scan page (\d+), left half$"), "fnd.where.left", ("n",)),
    (re.compile(r"^scan page (\d+), right half$"), "fnd.where.right", ("n",)),
    (re.compile(r"^page (\d+)$"), "fnd.where.page", ("n",)),
)


def _fill(text: str, params: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


def _get(lang: str, key: str, params: dict | None = None) -> str:
    v = FND.get(lang, {}).get(key) or ""
    return _fill(v, params) if v and params else v


def loc_where(w: str, lang: str) -> str:
    if not w or lang == "en":
        return w
    for rx, key, names in _WHERE:
        m = rx.match(w)
        if m:
            return _get(lang, key, dict(zip(names, m.groups()))) or w
    return w


def fnd_texts(f: dict, lang: str) -> tuple[str, str, str]:
    """(title, explanation, action) in the reader's language; falls back to the stored English."""
    title, expl, action = f.get("title", ""), f.get("explanation") or f.get("title", ""), f.get("action", "")
    key = f.get("key")
    if not key or lang == "en":
        return title, expl, action
    p = dict(f.get("params") or {})
    if p.get("how"):
        p["how"] = _get(lang, "fnd.print." + ("exact" if p["how"] == "exact" else "estimated")) or p["how"]
    t = _get(lang, f"fnd.{key}.t", p)
    if t and key.startswith("txt.") and f.get("kind") != "ocr":
        where = re.sub(r"^(PIL \d+ · |\d+(\.\d+)?\.?\s+)", "", f.get("section") or "")
        if where:
            t = f"{t} — {where}"
    e = _get(lang, f"fnd.{key}.e", p)
    if e and key.startswith("txt.") and f.get("kind") != "ocr" and p.get("cat"):
        imp = _get(lang, f"fnd.impact.{p['cat']}")
        if imp:
            e = f"{e} {imp}"
    a = _get(lang, f"fnd.{key}.a", p)
    if key.startswith("col.") and not p.get("std_action"):
        a = ""
    return t or title, e or expl, a or action


def localize_findings(findings: list[dict], lang: str) -> list[dict]:
    """Copies of the findings with title/explanation/action/category/positions in the reader's language."""
    if lang == "en":
        return findings
    out = []
    for f in findings:
        g = copy.copy(f)
        g["title"], g["explanation"], g["action"] = fnd_texts(f, lang)
        cat = CATEGORY_KEYS.get(f.get("category") or "")
        if cat:
            g["category"] = _get(lang, f"fnd.cat.{cat}") or f["category"]
        g["where_ref"] = loc_where(f.get("where_ref") or "", lang)
        g["where_des"] = loc_where(f.get("where_des") or "", lang)
        out.append(g)
    return out


# "fnd.print.exact" / "fnd.print.estimated" live in the frontend as print.exact/print.estimated;
# keep a tiny local copy so the exports need no second catalog.
FND["en"].setdefault("fnd.print.exact", "from the PDF")
FND["en"].setdefault("fnd.print.estimated", "estimated from the scan")
FND["fr"].setdefault("fnd.print.exact", "d'après le PDF")
FND["fr"].setdefault("fnd.print.estimated", "estimée depuis la numérisation")
FND["ar"].setdefault("fnd.print.exact", "من ملف PDF")
FND["ar"].setdefault("fnd.print.estimated", "مقدّرة من المسح")


# ---------------------------------------------------------------- report labels

STEP_NAMES_L = {
    "en": {1: "Level 1 — Approved text audit", 2: "Level 2 — Content comparison",
           3: "Level 3 — Punctuation & typography", 4: "Level 4 — Colour (shade standards)",
           5: "Level 5 — Barcodes", 6: "Level 6 — Graphics & layout", 7: "Level 7 — Text size, Braille & dieline"},
    "fr": {1: "Niveau 1 — Audit du texte approuvé", 2: "Niveau 2 — Comparaison du contenu",
           3: "Niveau 3 — Ponctuation et typographie", 4: "Niveau 4 — Couleur (teintes de référence)",
           5: "Niveau 5 — Codes-barres", 6: "Niveau 6 — Graphismes et mise en page",
           7: "Niveau 7 — Taille du texte, braille et découpe"},
    "ar": {1: "المستوى 1 — تدقيق النص المعتمد", 2: "المستوى 2 — مقارنة المحتوى",
           3: "المستوى 3 — الترقيم والأسلوب الطباعي", 4: "المستوى 4 — اللون (درجات مرجعية)",
           5: "المستوى 5 — الباركود", 6: "المستوى 6 — الرسوميات والتخطيط",
           7: "المستوى 7 — حجم النص والبرايل والقَص"},
}

STEP_SUBS_L = {
    "en": {1: "Errors in the approved text itself", 2: "Every word, in each language",
           3: "Punctuation, spacing, digit style", 4: "ΔE2000 against Standard / Light / Dark",
           5: "Decoded and checked against the product", 6: "Overlay against the approved artwork",
           7: "Minimum size, Braille, folds and cuts"},
    "fr": {1: "Erreurs dans le texte approuvé lui-même", 2: "Chaque mot, dans chaque langue",
           3: "Ponctuation, espaces, chiffres", 4: "ΔE2000 contre Standard / Claire / Foncée",
           5: "Décodés et vérifiés contre le produit", 6: "Superposition à la maquette approuvée",
           7: "Taille minimale, braille, plis et coupes"},
    "ar": {1: "أخطاء في النص المعتمد نفسه", 2: "كل كلمة، في كل لغة",
           3: "الترقيم والمسافات والأرقام", 4: "ΔE2000 مقابل القياسية / الفاتحة / الداكنة",
           5: "فُكّت وفُحصت مقابل المنتج", 6: "مطابقة فوق التصميم المعتمد",
           7: "الحد الأدنى للحجم والبرايل والطي والقص"},
}

L = {
    "en": {
        "report": "Comproof · Comparison report", "summary": "Summary", "level": "Level",
        "critical": "Critical", "major": "Major", "minor": "Minor", "info": "OCR noise",
        "confirmed": "Confirmed", "not_deviation": "Not a deviation", "pending": "Pending",
        "signatures": "Electronic signatures", "meaning": "Meaning", "name": "Name",
        "datetime": "Date/time (UTC)", "statement": "Statement", "approved": "Approved", "design": "Design",
        "what": "What changed", "action": "Action", "ai": "AI", "reviewer": "Reviewer",
        "no_findings": "No findings.", "no_shot": "no screenshot", "page": "Page",
        "findings": "Findings", "audit_info": "Audit info",
        "xl_head": ["ID", "Step", "Lang", "Severity", "Type", "Finding", "Section", "Category",
                    "Approved location", "Design location", "What changed", "Action", "Approved text",
                    "Design text", "AI verdict", "AI note", "Reviewer decision", "Reviewer comment",
                    "Reviewed by", "Reviewed at", "Approved screenshot", "Design screenshot"],
        "st": {"pending": "Pending", "confirmed": "Confirmed", "rejected": "Not a deviation"},
    },
    "fr": {
        "report": "Comproof · Rapport de comparaison", "summary": "Synthèse", "level": "Niveau",
        "critical": "Critique", "major": "Majeur", "minor": "Mineur", "info": "Bruit OCR",
        "confirmed": "Confirmé", "not_deviation": "Pas un écart", "pending": "En attente",
        "signatures": "Signatures électroniques", "meaning": "Signification", "name": "Nom",
        "datetime": "Date/heure (UTC)", "statement": "Déclaration", "approved": "Approuvé", "design": "Maquette",
        "what": "Ce qui a changé", "action": "Action", "ai": "IA", "reviewer": "Examinateur",
        "no_findings": "Aucun constat.", "no_shot": "pas de capture", "page": "Page",
        "findings": "Constats", "audit_info": "Informations d'audit",
        "xl_head": ["ID", "Niveau", "Langue", "Gravité", "Type", "Constat", "Rubrique", "Catégorie",
                    "Position (approuvé)", "Position (maquette)", "Ce qui a changé", "Action", "Texte approuvé",
                    "Texte de la maquette", "Verdict IA", "Note IA", "Décision de l'examinateur", "Commentaire",
                    "Examiné par", "Examiné le", "Capture (approuvé)", "Capture (maquette)"],
        "st": {"pending": "En attente", "confirmed": "Confirmé", "rejected": "Pas un écart"},
    },
    "ar": {
        "report": "Comproof · تقرير المقارنة", "summary": "الملخص", "level": "المستوى",
        "critical": "حرج", "major": "رئيسي", "minor": "ثانوي", "info": "ضوضاء OCR",
        "confirmed": "مؤكد", "not_deviation": "ليس انحرافًا", "pending": "قيد الانتظار",
        "signatures": "التوقيعات الإلكترونية", "meaning": "الدلالة", "name": "الاسم",
        "datetime": "التاريخ/الوقت (UTC)", "statement": "الإقرار", "approved": "المعتمد", "design": "التصميم",
        "what": "ما الذي تغيّر", "action": "الإجراء", "ai": "الذكاء الاصطناعي", "reviewer": "المراجع",
        "no_findings": "لا توجد ملاحظات.", "no_shot": "لا توجد صورة", "page": "صفحة",
        "findings": "الملاحظات", "audit_info": "بيانات التدقيق",
        "xl_head": ["المعرف", "المستوى", "اللغة", "الخطورة", "النوع", "الملاحظة", "القسم", "الفئة",
                    "الموضع (المعتمد)", "الموضع (التصميم)", "ما الذي تغيّر", "الإجراء", "النص المعتمد",
                    "نص التصميم", "حكم الذكاء الاصطناعي", "ملاحظة الذكاء الاصطناعي", "قرار المراجع", "التعليق",
                    "راجعه", "تاريخ المراجعة", "صورة المعتمد", "صورة التصميم"],
        "st": {"pending": "قيد الانتظار", "confirmed": "مؤكد", "rejected": "ليس انحرافًا"},
    },
}

META_KEYS = {
    "fr": {"Audit ID": "N° d'audit", "Company": "Société", "Product": "Produit", "Component": "Article",
           "Site": "Site", "Reference": "Référence", "Supplier": "Imprimeur", "Purpose": "Nature",
           "Started by": "Lancé par", "Started": "Lancé le", "Completed": "Terminé le", "Status": "Statut",
           "Approved file": "Fichier approuvé", "Test file": "Fichier d'essai", "Engine": "Moteur",
           "Result SHA-256": "SHA-256 du résultat", "AI models": "Modèles d'IA", "Levels run": "Niveaux exécutés",
           "AI notes": "Notes de l'IA", "Reading order": "Ordre de lecture", "Printed": "Généré le"},
    "ar": {"Audit ID": "رقم التدقيق", "Company": "الشركة", "Product": "المنتج", "Component": "المادة",
           "Site": "الموقع", "Reference": "المرجع", "Supplier": "المطبعة", "Purpose": "الغرض",
           "Started by": "بدأه", "Started": "بدأ في", "Completed": "اكتمل في", "Status": "الحالة",
           "Approved file": "الملف المعتمد", "Test file": "ملف الاختبار", "Engine": "المحرك",
           "Result SHA-256": "SHA-256 للنتيجة", "AI models": "نماذج الذكاء الاصطناعي", "Levels run": "المستويات المنفذة",
           "AI notes": "ملاحظات الذكاء الاصطناعي", "Reading order": "ترتيب القراءة", "Printed": "أُنشئ في"},
}

PURPOSE_L = {
    "en": {"proof": "Artwork proof", "printed_sample": "Printed sample", "supplier_proof": "Print-house proof",
           "master_review": "Review of the approved material (no test file)"},
    "fr": {"proof": "Épreuve de maquette", "printed_sample": "Échantillon imprimé", "supplier_proof": "BAT de l'imprimeur",
           "master_review": "Revue du matériel approuvé (sans fichier d'essai)"},
    "ar": {"proof": "بروفة تصميم", "printed_sample": "عينة مطبوعة", "supplier_proof": "بروفة المطبعة",
           "master_review": "مراجعة المادة المعتمدة (دون ملف اختبار)"},
}


LEVEL_SHORT_L = {
    "en": {1: "1 approved-text audit", 2: "2 content", 3: "3 punctuation and typography", 4: "4 colour",
           5: "5 barcodes", 6: "6 graphics", 7: "7 text size, Braille and dieline"},
    "fr": {1: "1 audit du texte approuvé", 2: "2 contenu", 3: "3 ponctuation et typographie", 4: "4 couleur",
           5: "5 codes-barres", 6: "6 graphismes", 7: "7 taille du texte, braille et découpe"},
    "ar": {1: "1 تدقيق النص المعتمد", 2: "2 المحتوى", 3: "3 الترقيم والأسلوب الطباعي", 4: "4 اللون",
           5: "5 الباركود", 6: "6 الرسوميات", 7: "7 حجم النص والبرايل والقص"},
}

MISC_L = {
    "en": {"not_used": "not used", "review_only": "— (review of the approved material only)"},
    "fr": {"not_used": "non utilisée", "review_only": "— (revue du matériel approuvé seul)"},
    "ar": {"not_used": "غير مستخدم", "review_only": "— (مراجعة المادة المعتمدة فقط)"},
}


STATUS_L = {
    "en": {"queued": "Queued", "running": "Running", "review": "In review", "approved": "Approved",
           "rejected": "Rejected", "failed": "Failed", "cancelled": "Cancelled"},
    "fr": {"queued": "En file", "running": "En cours", "review": "En examen", "approved": "Approuvée",
           "rejected": "Rejetée", "failed": "Échouée", "cancelled": "Annulée"},
    "ar": {"queued": "في الانتظار", "running": "قيد التشغيل", "review": "قيد المراجعة", "approved": "معتمدة",
           "rejected": "مرفوضة", "failed": "فشلت", "cancelled": "ملغاة"},
}

READING_L = {
    "en": "{lang}: approved {a}, test {t}, similarity {s}",
    "fr": "{lang} : approuvé {a}, essai {t}, similarité {s}",
    "ar": "{lang}: المعتمد {a}، الاختبار {t}، التشابه {s}",
}

FOOTER_L = {
    "en": "engine {e} · result SHA-256 {h}…",
    "fr": "moteur {e} · SHA-256 du résultat {h}…",
    "ar": "engine {e} · SHA-256 {h}…",
}

MEANING_L = {
    "en": {"reviewed": "Reviewed", "approved": "Approved", "rejected": "Rejected"},
    "fr": {"reviewed": "Examiné", "approved": "Approuvé", "rejected": "Rejeté"},
    "ar": {"reviewed": "تمت المراجعة", "approved": "معتمد", "rejected": "مرفوض"},
}


def meta_key(k: str, lang: str) -> str:
    return META_KEYS.get(lang, {}).get(k, k)


# Labels for the interactive HTML report (template chrome + its JavaScript).
HTML_LABELS = {
    "en": {
        "engine": "Engine", "generated": "Generated", "resultSha": "Result SHA-256", "pp": "pp",
        "confirm": "Confirm deviation", "reject": "Not a deviation", "reason": "Reason (required for “Not a deviation”)",
        "langs": {"eng": "English", "fra": "Français", "ara": "العربية"}, "viewer": "Side-by-side page viewer", "ai": "AI",
        "excluded": "Excluded from comparison", "sections": "Sections", "all": "All sections",
        "pending": "Undecided", "noise": "Show OCR noise", "expand": "Expand all", "collapse": "Collapse all",
        "shown": "{n} shown", "approved": "Approved", "design": "Design", "map": "Pack map",
        "hint": "Each dot is a finding. Click one to jump to it.",
        "what": "What changed", "act": "Action", "none": "No screenshot",
        "crit": "Critical", "major": "Major", "minor": "Minor", "info": "OCR noise",
        "st": {"pending": "Awaiting decision", "confirmed": "Confirmed", "rejected": "Not a deviation"},
        "notReady": "Not ready for print", "wip": "Review in progress", "ready": "Ready for print",
        "empty": "No findings match these filters.",
        "key": ["Approved only — removed in design", "Design only — added", "Missing text belongs here"],
        "open": "Open pages side by side", "search": "Search text, section or ID   ( / )", "close": "Close",
        "whyOpen": "{c} critical and {m} major open · {p} awaiting a decision", "whyPend": "{p} awaiting a decision",
        "doc": "Document", "page": "Page", "reasonCol": "Reason", "text": "Text",
        "aiReads": "— approved reads “{a}”, design reads “{d}”.",
        "aiv": {"real_difference": "real difference", "ocr_noise": "OCR noise", "unclear": "unclear"},
    },
    "fr": {
        "engine": "Moteur", "generated": "Généré le", "resultSha": "SHA-256 du résultat", "pp": "p.",
        "confirm": "Confirmer l'écart", "reject": "Pas un écart", "reason": "Raison (obligatoire pour « Pas un écart »)",
        "langs": {"eng": "English", "fra": "Français", "ara": "العربية"}, "viewer": "Pages côte à côte", "ai": "IA",
        "excluded": "Exclu de la comparaison", "sections": "Rubriques", "all": "Toutes les rubriques",
        "pending": "Sans décision", "noise": "Afficher le bruit OCR", "expand": "Tout développer", "collapse": "Tout replier",
        "shown": "{n} affichés", "approved": "Approuvé", "design": "Maquette", "map": "Carte du document",
        "hint": "Chaque point est un constat. Cliquez pour y aller.",
        "what": "Ce qui a changé", "act": "Action", "none": "Pas de capture",
        "crit": "Critique", "major": "Majeur", "minor": "Mineur", "info": "Bruit OCR",
        "st": {"pending": "Décision en attente", "confirmed": "Confirmé", "rejected": "Pas un écart"},
        "notReady": "Pas bon à tirer", "wip": "Examen en cours", "ready": "Bon à tirer",
        "empty": "Aucun constat ne correspond à ces filtres.",
        "key": ["Approuvé seulement — retiré de la maquette", "Maquette seulement — ajouté", "Le texte manquant va ici"],
        "open": "Ouvrir les pages côte à côte", "search": "Rechercher un texte, une rubrique ou un ID   ( / )", "close": "Fermer",
        "whyOpen": "{c} critiques et {m} majeurs ouverts · {p} en attente de décision", "whyPend": "{p} en attente de décision",
        "doc": "Document", "page": "Page", "reasonCol": "Raison", "text": "Texte",
        "aiReads": "— l'approuvé se lit « {a} », la maquette « {d} ».",
        "aiv": {"real_difference": "différence réelle", "ocr_noise": "bruit OCR", "unclear": "incertain"},
    },
    "ar": {
        "engine": "المحرك", "generated": "أُنشئ في", "resultSha": "SHA-256 للنتيجة", "pp": "صفحة",
        "confirm": "تأكيد الانحراف", "reject": "ليس انحرافًا", "reason": "السبب (مطلوب لـ «ليس انحرافًا»)",
        "langs": {"eng": "English", "fra": "Français", "ara": "العربية"}, "viewer": "عرض الصفحات جنبًا إلى جنب", "ai": "الذكاء الاصطناعي",
        "excluded": "المستبعد من المقارنة", "sections": "الأقسام", "all": "كل الأقسام",
        "pending": "بدون قرار", "noise": "عرض ضوضاء OCR", "expand": "فتح الكل", "collapse": "إغلاق الكل",
        "shown": "{n} معروض", "approved": "المعتمد", "design": "التصميم", "map": "خريطة المادة",
        "hint": "كل نقطة ملاحظة. اضغط للانتقال إليها.",
        "what": "ما الذي تغيّر", "act": "الإجراء", "none": "لا توجد صورة",
        "crit": "حرج", "major": "رئيسي", "minor": "ثانوي", "info": "ضوضاء OCR",
        "st": {"pending": "بانتظار القرار", "confirmed": "مؤكد", "rejected": "ليس انحرافًا"},
        "notReady": "غير جاهز للطباعة", "wip": "المراجعة جارية", "ready": "جاهز للطباعة",
        "empty": "لا توجد ملاحظات بهذه المعايير.",
        "key": ["في المعتمد فقط — محذوف من التصميم", "في التصميم فقط — مضاف", "النص المفقود يوضع هنا"],
        "open": "افتح الصفحات جنبًا إلى جنب", "search": "ابحث عن نص أو قسم أو معرف   ( / )", "close": "إغلاق",
        "whyOpen": "{c} حرج و{m} رئيسي مفتوح · {p} بانتظار القرار", "whyPend": "{p} بانتظار القرار",
        "doc": "المستند", "page": "صفحة", "reasonCol": "السبب", "text": "النص",
        "aiReads": "— المعتمد يُقرأ «{a}»، والتصميم «{d}».",
        "aiv": {"real_difference": "فرق حقيقي", "ocr_noise": "ضوضاء OCR", "unclear": "غير محسوم"},
    },
}
