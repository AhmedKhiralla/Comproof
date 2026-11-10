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


def test_arabic_numbers_from_ai_reading_match_western_numbers():
    from app.engine.ai_read import _words_in_box
    ws = _words_in_box("أكثر من ١ من كل ١٠ أشخاص والجرعة ١,٢٥ مجم", [0, 0, 400, 20], rtl=True)
    toks = compare.tokens_from_regions  # noqa: F841 (import check)
    design = " ".join(w.text for w in ws)
    assert compare._numbers(design) == compare._numbers("1 من كل 10 أشخاص والجرعة 1.25 مجم") == ["1.25", "10"]


def test_added_text_the_ai_reads_on_the_approved_image_is_not_a_deviation():
    added = "قم بتقشير كلا جانبي الغلاف برفق لفصلهما عند علامة السهم"
    f = compare.Finding("C108", 2, "ara", "added", "critical", "Added in design", "", added)
    f.ai = {"verdict": "real_difference", "impact": "major", "approved_reads": "٢ قم بتقشير كلا الغلاف برفق لفصلهما عند علامة السهم.",
            "design_reads": "٢ " + added, "explanation": "..."}
    pipeline.apply_review(f)
    assert f.severity == "minor" and f.ai["verdict"] == "unclear"
    g = compare.Finding("C9", 2, "eng", "added", "major", "Added", "",
                        "Ergotamine derivatives: exacerbation of peripheral circulatory disturbances")
    g.ai = {"verdict": "real_difference", "approved_reads": "Sulfonylureas: increased hypoglycaemic effect",
            "design_reads": g.des_text}
    pipeline.apply_review(g)
    assert g.severity == "major" and g.ai["verdict"] == "real_difference"   # genuinely added text stays
