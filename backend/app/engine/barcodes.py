"""Barcodes: decode, validate (GTIN check digit, GS1 data) and compare the test with the approved artwork.

Decoders, best first: zxing-cpp (all symbologies including GS1 DataMatrix), ZBar (1D codes and QR) and OpenCV
(EAN/UPC and QR). The image ships with zxing-cpp; the others are fallbacks.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import re
from datetime import date

import numpy as np
from PIL import Image

GS = "\x1d"
# GS1 application identifiers: fixed data length, or None for variable (ends with GS or end of data, max 20-30).
GS1_AI = {
    "00": ("SSCC", 18), "01": ("GTIN", 14), "02": ("Content GTIN", 14), "10": ("Batch / lot", None),
    "11": ("Production date", 6), "13": ("Packaging date", 6), "15": ("Best before", 6), "16": ("Sell by", 6),
    "17": ("Expiry date", 6), "21": ("Serial number", None), "22": ("Consumer product variant", None),
    "240": ("Additional product ID", None), "241": ("Customer part number", None), "30": ("Count", None),
    "710": ("NHRN Germany (PZN)", None), "711": ("NHRN France (CIP)", None), "712": ("NHRN Spain", None),
    "713": ("NHRN Brazil", None), "714": ("NHRN Portugal", None), "715": ("NHRN USA (NDC)", None),
    "7003": ("Expiration date and time", 10), "8006": ("Component ID", 18),
}
VARIABLE_AIS = {"10", "11", "13", "15", "16", "17", "21", "7003", "30"}   # differ between print runs by design
FAMILY = {"EAN-13": "EAN/UPC", "EAN-8": "EAN/UPC", "UPC-A": "EAN/UPC", "UPC-E": "EAN/UPC", "ISBN-13": "EAN/UPC"}


# --------------------------------------------------------------------------------------------- decoders
def _zxing(img: Image.Image) -> list[dict] | None:
    try:
        import zxingcpp
    except ImportError:
        return None
    out = []
    for r in zxingcpp.read_barcodes(img):
        fmt = str(r.format).split(".")[-1]
        name = {"EAN13": "EAN-13", "EAN8": "EAN-8", "UPCA": "UPC-A", "UPCE": "UPC-E", "QRCode": "QR",
                "DataMatrix": "DataMatrix", "Code128": "Code 128", "Code39": "Code 39", "ITF": "ITF",
                "PDF417": "PDF417", "DataBar": "GS1 DataBar", "MicroQRCode": "Micro QR"}.get(fmt, fmt)
        p = r.position
        xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
        ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
        text = r.text
        gs1 = bool(getattr(r, "content_type", None) and "GS1" in str(r.content_type)) or \
            str(getattr(r, "symbology_identifier", "")) in ("]d2", "]C1", "]Q3", "]e0")
        out.append({"symbology": name, "text": text, "gs1": gs1, "box": [min(xs), min(ys), max(xs), max(ys)],
                    "decoder": "zxing-cpp"})
    return out


_ZBAR = None
ZBAR_NAMES = {13: "EAN-13", 8: "EAN-8", 12: "UPC-A", 9: "UPC-E", 14: "ISBN-13", 25: "ITF", 39: "Code 39",
              128: "Code 128", 64: "QR", 34: "GS1 DataBar", 93: "Code 93", 57: "PDF417"}


def _zbar_lib():
    global _ZBAR
    if _ZBAR is None:
        path = ctypes.util.find_library("zbar") or "libzbar.so.0"
        try:
            lib = ctypes.CDLL(path)
        except OSError:
            _ZBAR = False
            return False
        lib.zbar_image_scanner_create.restype = ctypes.c_void_p
        lib.zbar_image_create.restype = ctypes.c_void_p
        lib.zbar_image_first_symbol.restype = ctypes.c_void_p
        lib.zbar_image_first_symbol.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_next.restype = ctypes.c_void_p
        lib.zbar_symbol_next.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_get_data.restype = ctypes.c_void_p
        lib.zbar_symbol_get_data.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_get_data_length.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_get_type.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_get_loc_size.argtypes = [ctypes.c_void_p]
        lib.zbar_symbol_get_loc_x.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        lib.zbar_symbol_get_loc_y.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        lib.zbar_image_scanner_set_config.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.zbar_image_set_format.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.zbar_image_set_size.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        lib.zbar_image_set_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        lib.zbar_scan_image.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.zbar_image_destroy.argtypes = [ctypes.c_void_p]
        lib.zbar_image_scanner_destroy.argtypes = [ctypes.c_void_p]
        _ZBAR = lib
    return _ZBAR


def _zbar(img: Image.Image) -> list[dict] | None:
    lib = _zbar_lib()
    if not lib:
        return None
    g = img.convert("L")
    w, h = g.size
    buf = ctypes.create_string_buffer(g.tobytes(), w * h)
    scanner = lib.zbar_image_scanner_create()
    lib.zbar_image_scanner_set_config(scanner, 0, 0, 1)          # all symbologies, ZBAR_CFG_ENABLE
    zimg = lib.zbar_image_create()
    lib.zbar_image_set_format(zimg, 0x30303859)                  # 'Y800' grey
    lib.zbar_image_set_size(zimg, w, h)
    lib.zbar_image_set_data(zimg, ctypes.cast(buf, ctypes.c_void_p), w * h, None)
    out = []
    try:
        if lib.zbar_scan_image(scanner, zimg) > 0:
            sym = lib.zbar_image_first_symbol(zimg)
            while sym:
                n = lib.zbar_symbol_get_data_length(sym)
                raw = ctypes.string_at(lib.zbar_symbol_get_data(sym), n)
                text = raw.decode("utf-8", "replace")
                k = lib.zbar_symbol_get_loc_size(sym)
                xs = [lib.zbar_symbol_get_loc_x(sym, i) for i in range(k)] or [0]
                ys = [lib.zbar_symbol_get_loc_y(sym, i) for i in range(k)] or [0]
                name = ZBAR_NAMES.get(lib.zbar_symbol_get_type(sym), f"type {lib.zbar_symbol_get_type(sym)}")
                out.append({"symbology": name, "text": text, "gs1": text.startswith("]C1") or GS in text,
                            "box": [min(xs), min(ys), max(xs), max(ys)], "decoder": "zbar"})
                sym = lib.zbar_symbol_next(sym)
    finally:
        lib.zbar_image_destroy(zimg)
        lib.zbar_image_scanner_destroy(scanner)
    return out


def _opencv(img: Image.Image) -> list[dict]:
    import cv2
    a = np.asarray(img.convert("RGB"))
    out = []
    try:
        det = cv2.barcode.BarcodeDetector()
        ok, texts, types, pts = det.detectAndDecodeWithType(a)
        if ok:
            for t, ty, p in zip(texts, types, pts):
                if t:
                    xs, ys = p[:, 0], p[:, 1]
                    out.append({"symbology": {"EAN_13": "EAN-13", "EAN_8": "EAN-8", "UPC_A": "UPC-A",
                                              "UPC_E": "UPC-E"}.get(ty, ty), "text": t, "gs1": False,
                                "box": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
                                "decoder": "opencv"})
    except Exception:  # noqa: BLE001
        pass
    try:
        qr = cv2.QRCodeDetector()
        ok, texts, pts, _ = qr.detectAndDecodeMulti(a)
        if ok:
            for t, p in zip(texts, pts):
                if t:
                    out.append({"symbology": "QR", "text": t, "gs1": False,
                                "box": [float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()),
                                        float(p[:, 1].max())], "decoder": "opencv"})
    except Exception:  # noqa: BLE001
        pass
    return out


def decoders() -> list[str]:
    names = []
    try:
        import zxingcpp  # noqa: F401
        names.append("zxing-cpp")
    except ImportError:
        pass
    if _zbar_lib():
        names.append("zbar")
    names.append("opencv")
    return names


def decode_image(img: Image.Image) -> list[dict]:
    """All codes on one page. Tries the original and a 2x enlargement (small codes on 300 dpi renders)."""
    found: list[dict] = []
    for scale in (1, 2):
        im = img if scale == 1 else img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        res = _zxing(im)
        if res is None:
            res = _zbar(im) or []
            if not res:
                res = _opencv(im)
        for r in res:
            r["box"] = [v / scale for v in r["box"]]
            if not any(r["text"] == f["text"] and r["symbology"] == f["symbology"] for f in found):
                found.append(r)
        if found:
            break
    return found


# --------------------------------------------------------------------------------------------- validation
def gtin_check_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def gtin14(digits: str) -> str:
    return digits.zfill(14) if digits.isdigit() else digits


def parse_gs1(text: str) -> tuple[dict, list[str]]:
    """GS1 element string -> {AI: value}, problems. Accepts raw (GS separated) and '(01)...' human form."""
    t = text
    for prefix in ("]d2", "]C1", "]Q3", "]e0", "]J1"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    problems: list[str] = []
    out: dict = {}
    i = 0
    if t.startswith("("):
        for ai, val in re.findall(r"\((\d{2,4})\)([^(]*)", t):
            out[ai] = val
        i = len(t)
    while i < len(t):
        if t[i] == GS:
            i += 1
            continue
        ai = next((a for a in sorted(GS1_AI, key=len, reverse=True) if t.startswith(a, i)), None)
        if ai is None:
            problems.append(f"Unknown application identifier at “{t[i:i + 4]}”.")
            break
        i += len(ai)
        n = GS1_AI[ai][1]
        if n:
            val = t[i:i + n]
            if len(val) < n:
                problems.append(f"({ai}) {GS1_AI[ai][0]} is too short.")
            i += n
        else:
            j = t.find(GS, i)
            j = len(t) if j < 0 else j
            val = t[i:j]
            i = j
        out[ai] = val
    for ai in ("11", "13", "15", "16", "17"):
        v = out.get(ai)
        if v and v.isdigit() and len(v) == 6:
            yy, mm, dd = int(v[:2]), int(v[2:4]), int(v[4:])
            try:
                if not 1 <= mm <= 12:
                    raise ValueError
                if dd:
                    date(2000 + yy, mm, dd)
            except ValueError:
                problems.append(f"({ai}) {GS1_AI[ai][0]} “{v}” is not a valid date.")
    if "01" in out and not gtin_check_ok(out["01"]):
        problems.append(f"(01) GTIN {out['01']} has a wrong check digit.")
    return out, problems


def describe(code: dict) -> dict:
    """Add GTIN / GS1 meaning to a decoded code."""
    c = dict(code)
    sym, text = c["symbology"], c["text"]
    c["problems"] = []
    if sym in ("EAN-13", "EAN-8", "UPC-A", "UPC-E", "ISBN-13"):
        c["gtin"] = gtin14(text)
        if not gtin_check_ok(text):
            c["problems"].append(f"{sym} {text} has a wrong check digit.")
    elif c.get("gs1") or (sym in ("DataMatrix", "Code 128", "GS1 DataBar", "QR") and re.match(r"^(\]..)?(\(01\)|01\d{14})", text)):
        c["gs1"] = True
        c["fields"], c["problems"] = parse_gs1(text)
        if "01" in c["fields"]:
            c["gtin"] = c["fields"]["01"]
    return c


# --------------------------------------------------------------------------------------------- comparison
def compare_sets(ref: list[dict], test: list[dict], purpose: str, product_gtin: str | None) -> tuple[list[dict], list[dict]]:
    """Returns (table rows, problems). Each problem: {severity, title, detail, ref, test}."""
    ref = [describe(c) for c in ref]
    test = [describe(c) for c in test]
    used: set = set()
    rows, problems = [], []

    def family(c):
        return FAMILY.get(c["symbology"], c["symbology"])

    def key_match(a, b):
        if family(a) != family(b):
            return False
        if a.get("gtin") and b.get("gtin"):
            return gtin14(a["gtin"]) == gtin14(b["gtin"])
        return a["text"] == b["text"]

    for r in ref:
        j = next((j for j, t in enumerate(test) if j not in used and key_match(r, t)), None)
        if j is None:
            j = next((j for j, t in enumerate(test) if j not in used and family(t) == family(r)), None)
        t = test[j] if j is not None else None
        if j is not None:
            used.add(j)
        row = {"symbology": r["symbology"], "approved": r["text"], "test": t["text"] if t else None,
               "gtin": r.get("gtin"), "fields_approved": r.get("fields"), "fields_test": t.get("fields") if t else None,
               "ref_box": r["box"], "ref_page": r.get("page"), "test_box": t["box"] if t else None,
               "test_page": t.get("page") if t else None, "status": "match"}
        if t is None:
            row["status"] = "missing"
            problems.append({"severity": "critical", "title": f"{r['symbology']} barcode missing or unreadable",
                             "detail": f"The approved artwork has a {r['symbology']} code ({r['text']}); none was "
                                       "read on the test file.", "row": row})
        elif r.get("gs1") and t.get("gs1"):
            fa, ft = r.get("fields", {}), t.get("fields", {})
            fixed_diff = [ai for ai in set(fa) | set(ft) if ai not in VARIABLE_AIS and fa.get(ai) != ft.get(ai)]
            var_diff = [ai for ai in set(fa) | set(ft) if ai in VARIABLE_AIS and fa.get(ai) != ft.get(ai)]
            if fixed_diff:
                row["status"] = "changed"
                problems.append({"severity": "critical", "title": f"{r['symbology']} data changed",
                                 "detail": "; ".join(f"({ai}) {GS1_AI.get(ai, ('AI',))[0]}: approved "
                                                     f"“{fa.get(ai, '—')}”, test “{ft.get(ai, '—')}”" for ai in
                                                     sorted(fixed_diff)), "row": row})
            elif var_diff:
                row["status"] = "variable_data"
                if purpose == "proof":
                    problems.append({"severity": "minor", "title": f"{r['symbology']} variable data differs",
                                     "detail": "; ".join(f"({ai}) {GS1_AI.get(ai, ('AI',))[0]}: approved "
                                                         f"“{fa.get(ai, '—')}”, test “{ft.get(ai, '—')}”"
                                                         for ai in sorted(var_diff))
                                               + ". Batch, expiry and serial normally change per print run.",
                                     "row": row})
        elif r["text"] != t["text"]:
            row["status"] = "changed"
            problems.append({"severity": "critical", "title": f"{r['symbology']} content changed",
                             "detail": f"Approved “{r['text']}”, test “{t['text']}”.", "row": row})
        for c, who in ((r, "approved artwork"), (t, "test file")):
            for p in (c or {}).get("problems", []):
                problems.append({"severity": "critical" if "check digit" in p else "major",
                                 "title": f"Invalid barcode data on the {who}", "detail": p, "row": row})
        if product_gtin and t and t.get("gtin") and gtin14(t["gtin"]) != gtin14(product_gtin):
            problems.append({"severity": "critical", "title": "GTIN does not match the product record",
                             "detail": f"Test code GTIN {t['gtin']}, product record GTIN {product_gtin}.", "row": row})
        rows.append(row)
    for j, t in enumerate(test):
        if j in used:
            continue
        row = {"symbology": t["symbology"], "approved": None, "test": t["text"], "gtin": t.get("gtin"),
               "fields_approved": None, "fields_test": t.get("fields"), "ref_box": None, "ref_page": None,
               "test_box": t["box"], "test_page": t.get("page"), "status": "added"}
        problems.append({"severity": "major", "title": f"Extra {t['symbology']} barcode on the test file",
                         "detail": f"“{t['text']}” is not on the approved artwork.", "row": row})
        for p in t.get("problems", []):
            problems.append({"severity": "critical" if "check digit" in p else "major",
                             "title": "Invalid barcode data on the test file", "detail": p, "row": row})
        rows.append(row)
    return rows, problems


def decode_document(doc) -> list[dict]:
    out = []
    for p in doc.pages:
        for c in decode_image(p.image):
            c["page"] = p.index
            out.append(c)
    return out
