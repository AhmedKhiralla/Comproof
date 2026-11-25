"""Braille reading: real Braille is read; round letters of small bold print are not Braille."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.engine import ingest, layout, print_checks as pc
from print_fixtures import braille_image


def _doc(img):
    return ingest.Document(name="x", kind="image", pages=[ingest.Page(index=0, image=img, words=None, source_dpi=300)])


def _text_page(dpi=300):
    """Dense small bold French text scanned slightly soft, like a cosmetic label: the bowls of e, o, a, d look like
    Braille dots to a blob detector."""
    px = dpi / 25.4
    im = Image.new("RGB", (int(150 * px), int(40 * px)), (255, 255, 255))
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(2.4 * px))
    lines = ["Grâce à ses actifs définissants et enrichie en", "complexe d'huile de coco, notre formule aide à",
             "redessiner les boucles et les protéger de l'humidité."]
    for i, t in enumerate(lines):
        d.text((6 * px, (4 + i * 3.4) * px), t, fill=(40, 25, 20), font=font)
    return im.filter(ImageFilter.GaussianBlur(1.2))


def test_real_braille_is_read():
    probs, info = pc.braille_check(_doc(braille_image("nerkardou 25")), "Nerkardou 2.5 mg", [], True)
    assert info["found"] and info["found"][0]["text"].startswith("nerkardou"), info
    assert not probs, probs


def test_wrong_braille_name_is_still_critical():
    probs, _ = pc.braille_check(_doc(braille_image("paracet")), "Nerkardou 2.5 mg", [], True)
    assert [p["key"] for p in probs] == ["pr.br_name"] and probs[0]["severity"] == "critical", probs


def test_printed_text_is_not_braille():
    img = _text_page()
    assert pc.read_braille(pc.find_dots(img, 300), 300), "fixture must look like Braille to the dot reader"
    doc = _doc(img)
    regions = layout.analyse_page(img, 0, layout.DEFAULT_EXCLUDE_PHRASES, latin="fra")[0]
    for regs in (regions, None):            # with the OCR text boxes, and without them (pattern check alone)
        probs, info = pc.braille_check(doc, "Test SCITRA 01", [], False, regs)
        assert not info["found"], info
        assert all(p["severity"] != "critical" for p in probs), probs
