"""How AI review answers change a finding: never upwards, and 'noise' only when the AI's own readings agree."""
from app.engine import compare, pipeline


def _f(sev="major", step=2, lang="ara", ref="نركاردو", des="تركاردو"):
    return compare.Finding("C1", step, lang, "changed", sev, "t", ref, des)


def test_ai_cannot_raise_severity():
    f = _f("major")
    f.ai = {"verdict": "real_difference", "impact": "critical", "approved_reads": "نركاردو", "design_reads": "نركاردوا"}
    pipeline.apply_review(f)
    assert f.severity == "major"


def test_noise_needs_matching_readings():
    f = _f("critical")
    f.ai = {"verdict": "real_difference", "impact": "critical", "approved_reads": "نركاردو", "design_reads": "نركاردو",
            "explanation": "The approved reads Turkarduo..."}
    pipeline.apply_review(f)                       # its own readings agree, whatever it concluded
    assert f.severity == "info" and f.ai["verdict"] == "ocr_noise"
    g = _f("critical", lang="eng", ref="2.5 mg", des="25 mg")
    g.ai = {"verdict": "ocr_noise", "approved_reads": "2.5 mg", "design_reads": "25 mg"}
    pipeline.apply_review(g)                       # says noise but reads different numbers: stays open
    assert g.severity == "critical" and g.ai["verdict"] == "unclear"


def test_level3_noise_requires_exact_match():
    f = _f("minor", step=3, lang="eng", ref="10 mg", des="10mg")
    f.ai = {"verdict": "ocr_noise", "approved_reads": "10 mg", "design_reads": "10mg"}
    pipeline.apply_review(f)
    assert f.severity == "minor" and f.ai["verdict"] == "unclear"
