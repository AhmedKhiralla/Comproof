"""Default feature toggles, engine settings and terminology for new companies."""
from __future__ import annotations

# Feature toggles, grouped for the settings screen.
FEATURES: dict[str, dict] = {
    # Audit levels
    "step1_master_audit": {"group": "levels", "default": True},   # scientific / consistency audit of the approved text
    "step3_typography":   {"group": "levels", "default": True},   # punctuation, spacing, case, digit style
    # Review rules (21 CFR Part 11 procedural controls)
    "four_eyes":          {"group": "review", "default": True},   # the approver must not be the person who reviewed
    "all_decided":        {"group": "review", "default": True},   # every finding needs a decision before approval
    # AI (needs a provider key on the server)
    "ai_review":          {"group": "ai", "default": True},       # AI checks each finding's two screenshots
    "ai_science":         {"group": "ai", "default": True},       # AI pharmacist review of the approved text
    "ai_reading":         {"group": "ai", "default": False},      # AI transcribes scans (more accurate, costs more)
}


def effective_features(stored: dict | None) -> dict[str, bool]:
    base = {k: v["default"] for k, v in FEATURES.items()}
    for k, v in (stored or {}).items():
        if k in base and isinstance(v, bool):
            base[k] = v
    return base


# Engine settings per company (tenants.engine).
ENGINE_DEFAULTS: dict = {
    "provider": None,             # AI provider name; None = first configured
    "reading_provider": None,     # provider for reading scans; None = same as provider
    "exclude_phrases": [],        # extra administrative text to ignore, one phrase per entry
    "rotated_text": "auto",       # leaflets: ignore rotated print-house strips; other packaging: read them
}


def effective_engine(stored: dict | None) -> dict:
    out = dict(ENGINE_DEFAULTS)
    for k, v in (stored or {}).items():
        if k in out:
            out[k] = v
    return out


# Renamable terms. Each company can change the words used across the app.
TERMS: dict[str, dict[str, str]] = {
    "component":  {"en": "Packaging component", "ar": "مادة تعبئة"},
    "artwork":    {"en": "Approved artwork", "ar": "التصميم المعتمد"},
    "comparison": {"en": "Comparison", "ar": "مقارنة"},
    "supplier":   {"en": "Print house", "ar": "المطبعة"},
}


def effective_terms(stored: dict | None) -> dict[str, dict[str, str]]:
    out = {k: dict(v) for k, v in TERMS.items()}
    for key, langs in (stored or {}).items():
        if key in out and isinstance(langs, dict):
            for lang in ("en", "ar"):
                val = langs.get(lang)
                if isinstance(val, str) and val.strip():
                    out[key][lang] = val.strip()[:60]
    return out
