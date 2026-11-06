"""Colour: shade standards (Standard / Light / Dark) and checking samples against them.

Inputs, from most to least reliable:
  spectro       CxF3 or CGATS measurements (L*a*b*) per named patch          -> "measured"
  scan_target   flatbed scan with a ColorChecker Classic in the image        -> "calibrated"
  scan          flatbed scan, normalised to the unprinted paper white        -> "relative" (same scanner and settings)
  photo         phone or tablet photo                                        -> "screening" (never pass / fail)

How a shade set is analysed
  1. Light and Dark scans are aligned to the Standard (ORB features + RANSAC homography).
  2. Each scan is calibrated (colour target if found, otherwise paper white).
  3. Solid ink areas are found on the Standard (flat, non-paper pixels clustered in L*a*b*); each ink keeps a set
     of sample points, so exactly the same spots are measured on every shade and every later sample.
  4. Each ink is measured on the three scans and the order is verified: Light must be lighter than the Standard
     and Dark darker, otherwise the cards are mislabelled (or the shade does not differ for that ink).

How a sample is judged, per ink
  The Dark -> Standard -> Light measurements form a path in L*a*b*. The sample passes when its closest point lies on
  that path (not beyond Dark or Light) and it is no further from the path than the tolerance (ΔE). ΔE2000 to the
  Standard, Light and Dark is always reported. Inks whose Light and Dark do not differ ("not shade-controlled") pass
  when ΔE2000 to the Standard is within the tolerance.
"""
from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

COLOUR_VERSION = "1.0.0"
MIN_SHADE_DE = 0.8          # ΔE00 below which Light/Dark are treated as "the same as the Standard" for that ink
ORDER_MARGIN_L = 0.3        # L* units of slack when checking Light > Standard > Dark
MAX_INKS = 10
WORK_SIDE = 1100            # analysis resolution (longest side, pixels)

CONFIDENCE = {"spectro": "measured", "scan_target": "calibrated", "scan": "relative", "photo": "screening"}

# ColorChecker Classic (post-2014) reference values, sRGB D65, row by row from "dark skin" to "black".
COLORCHECKER_SRGB = np.array([
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52)], float)


class ColourError(Exception):
    pass


# ----------------------------------------------------------------------------------------------- colour maths
def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb in 0..255 (any shape [...,3]) -> CIE L*a*b* (D65)."""
    from skimage.color import rgb2lab
    a = np.clip(np.asarray(rgb, float) / 255.0, 0, 1)
    shape = a.shape
    return rgb2lab(a.reshape(-1, 1, 3)).reshape(shape)


def de00(a, b) -> float:
    from skimage.color import deltaE_ciede2000
    return float(deltaE_ciede2000(np.asarray(a, float).reshape(1, 3), np.asarray(b, float).reshape(1, 3))[0])


def lab_dict(v) -> dict:
    return {"L": round(float(v[0]), 2), "a": round(float(v[1]), 2), "b": round(float(v[2]), 2)}


def lab_vec(d: dict) -> np.ndarray:
    return np.array([d["L"], d["a"], d["b"]], float)


def colour_name(lab) -> str:
    L, a, b = (float(x) for x in lab)
    C = math.hypot(a, b)
    if C < 8:
        return "Black" if L < 25 else "Dark grey" if L < 50 else "Grey" if L < 80 else "Light grey"
    h = (math.degrees(math.atan2(b, a)) + 360) % 360
    names = [(15, "Magenta"), (50, "Red"), (75, "Orange"), (105, "Yellow"), (125, "Yellow-green"), (190, "Green"),
             (235, "Cyan"), (305, "Blue"), (335, "Purple"), (360, "Magenta")]
    name = next(n for lim, n in names if h < lim)
    if name == "Orange" and L < 45:
        name = "Brown"
    return ("Dark " + name.lower()) if L < 30 else ("Light " + name.lower()) if L > 88 else name


# ----------------------------------------------------------------------------------------------- loading
def load_image(path: str) -> tuple[np.ndarray, float]:
    """First page of a PDF or an image, as RGB uint8, plus the resolution in dpi."""
    from . import ingest
    doc = ingest.load(path)
    if not doc.pages:
        raise ColourError("The file has no page to measure.")
    p = doc.pages[0]
    dpi = p.source_dpi if p.source_dpi and p.source_dpi > 72 else 300.0
    return np.asarray(p.image.convert("RGB")), float(dpi)


def _small(rgb: np.ndarray, side: int = WORK_SIDE) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    f = min(1.0, side / max(h, w))
    if f >= 1.0:
        return rgb, 1.0
    import cv2
    return cv2.resize(rgb, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA), f


def descreen(rgb: np.ndarray, dpi: float) -> np.ndarray:
    """Average out the halftone screen: a scan of print is dots, the eye (and a spectro aperture) sees the mix."""
    import cv2
    sigma = max(1.0, dpi * 0.35 / 25.4)        # about 0.35 mm
    return cv2.GaussianBlur(rgb, (0, 0), sigma)


# ----------------------------------------------------------------------------------------------- alignment
def align(src: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, dict]:
    """Warp src onto ref's geometry. Returns (warped src, info)."""
    import cv2
    s_small, fs = _small(src, 1600)
    r_small, fr = _small(ref, 1600)
    g1 = cv2.cvtColor(s_small, cv2.COLOR_RGB2GRAY)
    g2 = cv2.cvtColor(r_small, cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(6000)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    info = {"method": "features", "matches": 0, "inliers": 0, "ok": False}
    if d1 is not None and d2 is not None and len(k1) > 20 and len(k2) > 20:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(d1, d2, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.78 * n.distance]
        info["matches"] = len(good)
        if len(good) >= 12:
            p1 = np.float32([k1[m.queryIdx].pt for m in good]) / fs
            p2 = np.float32([k2[m.trainIdx].pt for m in good]) / fr
            H, mask = cv2.findHomography(p1, p2, cv2.RANSAC, 4.0)
            if H is not None:
                inl = int(mask.sum())
                info["inliers"] = inl
                info["inlier_ratio"] = round(inl / len(good), 3)
                if inl >= 15 and inl / len(good) >= 0.25:
                    h, w = ref.shape[:2]
                    info["H"] = H.tolist()
                    warped = cv2.warpPerspective(src, H, (w, h), flags=cv2.INTER_LINEAR,
                                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
                    info["ok"] = True
                    return warped, info
    # Fallback: same aspect ratio -> plain resize (cards scanned edge to edge)
    import cv2 as _cv
    hs, ws = src.shape[:2]
    hr, wr = ref.shape[:2]
    if abs(ws / hs - wr / hr) < 0.02:
        info.update(method="resize", ok=True, H=[[wr / ws, 0, 0], [0, hr / hs, 0], [0, 0, 1]])
        return _cv.resize(src, (wr, hr), interpolation=_cv.INTER_AREA), info
    return src, info


# ----------------------------------------------------------------------------------------------- calibration
def paper_white(rgb: np.ndarray) -> np.ndarray | None:
    """Colour of the unprinted substrate: the brightest low-chroma pixels."""
    small, _ = _small(rgb, 800)
    px = small.reshape(-1, 3).astype(float)
    lum = px.mean(1)
    chroma = px.max(1) - px.min(1)
    cand = px[(chroma < 80)]                   # exclude saturated inks; a colour cast can tint the paper
    if len(cand) < 50:
        return None
    thr = np.percentile(cand.mean(1), 97)
    top = cand[cand.mean(1) >= thr]
    if len(top) < 20 or top.mean() < 120:
        return None
    return np.median(top, axis=0)


def normalise_white(rgb: np.ndarray, white: np.ndarray | None, target: float = 245.0) -> np.ndarray:
    if white is None:
        return rgb
    gain = target / np.maximum(white, 1.0)
    return np.clip(rgb.astype(float) * gain, 0, 255).astype(np.uint8)


def find_colorchecker(rgb: np.ndarray) -> dict | None:
    """Best-effort detection of a ColorChecker Classic (4 x 6 patches). Returns a 3x4 correction matrix
    (measured RGB -> reference sRGB) and the fit residual, or None."""
    import cv2
    small, f = _small(rgb, 1400)
    g = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 20, 60)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(255 - edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    squares = []
    area_img = small.shape[0] * small.shape[1]
    for c in cnts:
        a = cv2.contourArea(c)
        if a < area_img * 0.0004 or a > area_img * 0.05:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not 0.75 < w / h < 1.33 or a / (w * h) < 0.75:
            continue
        squares.append((x + w / 2, y + h / 2, w, h))
    if len(squares) < 20:
        return None
    dedup: list = []                          # the same patch can be found as two nested contours
    for sq in sorted(squares, key=lambda q: -q[2]):
        if all(math.hypot(sq[0] - o[0], sq[1] - o[1]) > 0.35 * o[2] for o in dedup):
            dedup.append(sq)
    squares = dedup
    # The chart is the largest cluster of similar squares that touch their neighbours (patch + gap apart).
    best_group: list = []
    used = [False] * len(squares)
    for i in range(len(squares)):
        if used[i]:
            continue
        group, todo = [], [i]
        used[i] = True
        while todo:
            a = todo.pop()
            group.append(a)
            xa, ya, wa, ha = squares[a]
            for b in range(len(squares)):
                if used[b]:
                    continue
                xb, yb, wb, hb = squares[b]
                if 0.75 < wb / wa < 1.33 and math.hypot(xa - xb, ya - yb) < 1.7 * max(wa, wb):
                    used[b] = True
                    todo.append(b)
        if len(group) > len(best_group):
            best_group = group
    squares = [squares[i] for i in best_group]
    if not 20 <= len(squares) <= 30:
        return None
    sizes = np.median([s[2] for s in squares])
    pts = np.array([(s[0], s[1]) for s in squares], float)
    # Fit the grid: principal axes of the patch centres.
    mean = pts.mean(0)
    step = float(np.median([min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in pts if q is not p and
                                 (p[0], p[1]) != (q[0], q[1])) for p in pts]))
    u, sv, vt = np.linalg.svd(pts - mean)
    proj = (pts - mean) @ vt.T
    best = None
    for long_axis in (0, 1):
        cols_axis, rows_axis = long_axis, 1 - long_axis
        cx = np.round((proj[:, cols_axis] - proj[:, cols_axis].min()) / step).astype(int)
        cy = np.round((proj[:, rows_axis] - proj[:, rows_axis].min()) / step).astype(int)
        if cx.max() != 5 or cy.max() != 3:
            continue
        grid = {}
        for (i, j), s in zip(zip(cy, cx), squares):
            grid.setdefault((i, j), s)
        if len(grid) < 22:
            continue
        meas = np.zeros((4, 6, 3))
        ok = np.zeros((4, 6), bool)
        for (i, j), s in grid.items():
            x, y, w, h = s
            x0, x1 = int(x - w * 0.25), int(x + w * 0.25)
            y0, y1 = int(y - h * 0.25), int(y + h * 0.25)
            meas[i, j] = np.median(small[y0:y1, x0:x1].reshape(-1, 3), axis=0)
            ok[i, j] = True
        for flip_r in (False, True):
            for flip_c in (False, True):
                m = meas[::-1] if flip_r else meas
                m = m[:, ::-1] if flip_c else m
                o = ok[::-1] if flip_r else ok
                o = o[:, ::-1] if flip_c else o
                M = m.reshape(-1, 3)[o.reshape(-1)]
                R = COLORCHECKER_SRGB[o.reshape(-1)]
                X = np.hstack([M, np.ones((len(M), 1))])
                A, *_ = np.linalg.lstsq(X, R, rcond=None)
                fit = X @ A
                res = float(np.mean([de00(srgb_to_lab(a), srgb_to_lab(b)) for a, b in zip(fit, R)]))
                if best is None or res < best["residual"]:
                    best = {"matrix": A.T.tolist(), "residual": round(res, 2), "patches": int(o.sum())}
    if best and best["residual"] < 6.0:
        return best
    return None


def apply_matrix(rgb: np.ndarray, matrix) -> np.ndarray:
    A = np.asarray(matrix, float)                     # 3 x 4
    px = rgb.reshape(-1, 3).astype(float)
    out = px @ A[:, :3].T + A[:, 3]
    return np.clip(out, 0, 255).reshape(rgb.shape).astype(np.uint8)


def calibrate(rgb: np.ndarray, source: str) -> tuple[np.ndarray, dict]:
    if source == "scan_target":
        cc = find_colorchecker(rgb)
        if cc:
            return apply_matrix(rgb, cc["matrix"]), {"method": "colour_target", "residual_de00": cc["residual"],
                                                     "patches": cc["patches"]}
        white = paper_white(rgb)
        return normalise_white(rgb, white), {"method": "paper_white", "note": "Colour target not found in the scan; "
                                             "the paper white was used instead (relative result)."}
    white = paper_white(rgb)
    return normalise_white(rgb, white), {"method": "paper_white" if white is not None else "none",
                                         "paper_rgb": [round(float(x), 1) for x in white] if white is not None else None}


# ----------------------------------------------------------------------------------------------- ink areas
def find_inks(rgb: np.ndarray, dpi: float) -> list[dict]:
    """Solid colour areas on the (calibrated) Standard. Each ink: name, box, area share, sample points
    (full-resolution coordinates of the Standard)."""
    import cv2
    small, f = _small(descreen(rgb, dpi))
    lab = srgb_to_lab(small)
    L = lab[..., 0]
    # flat = low local variation of L*, a*, b*
    var = np.zeros(L.shape)
    for ch in range(3):
        x = lab[..., ch]
        m = cv2.blur(x, (7, 7))
        var += cv2.blur(x * x, (7, 7)) - m * m
    flat = np.sqrt(np.maximum(var, 0)) < 3.0
    white = paper_white(small)
    if white is not None:
        wlab = srgb_to_lab(white)
        dist = np.sqrt(((lab - wlab) ** 2).sum(-1))
        ink = flat & (dist > 8)
    else:
        ink = flat & (L < 92)
    ink = cv2.erode(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    pix = lab[ink]
    if len(pix) < 200:
        raise ColourError("No solid ink areas were found on the Standard. Use a scan of the printed card at 300 dpi "
                          "or more, or import spectrophotometer measurements.")
    sample = pix[np.random.default_rng(0).choice(len(pix), min(len(pix), 40000), replace=False)].astype(np.float32)
    k = min(MAX_INKS + 2, max(2, len(sample) // 2000))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2)
    _, labels, centres = cv2.kmeans(sample, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    # merge clusters closer than ΔE00 5
    centres = [c for c in centres]
    groups: list[list[int]] = []
    for i, c in enumerate(centres):
        for g in groups:
            if de00(centres[g[0]], c) < 5.0:
                g.append(i)
                break
        else:
            groups.append([i])
    merged = [np.mean([centres[i] for i in g], axis=0) for g in groups]
    # assign every ink pixel to the nearest merged centre
    flat_lab = lab.reshape(-1, 3)
    d = np.stack([np.sqrt(((flat_lab - c) ** 2).sum(1)) for c in merged], 1)
    nearest = d.argmin(1).reshape(L.shape)
    near_ok = d.min(1).reshape(L.shape) < 6.0
    inks = []
    min_px = max(120, int(0.0004 * L.size))
    for gi, c in enumerate(merged):
        mask = (ink & near_ok & (nearest == gi)).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8))
        n = int(mask.sum())
        if n < min_px:
            continue
        ys, xs = np.nonzero(mask)
        idx = np.random.default_rng(gi).choice(len(xs), min(len(xs), 400), replace=False)
        pts = [[int(xs[i] / f), int(ys[i] / f)] for i in idx]
        # main area box: the largest connected component
        cnt, lab_cc, stats, _ = cv2.connectedComponentsWithStats(mask)
        j = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) if cnt > 1 else 0
        x, y, w, h = (int(v / f) for v in stats[j, :4]) if cnt > 1 else (0, 0, 0, 0)
        inks.append({"centre": c, "pixels": n, "points": pts, "box": [x, y, x + w, y + h],
                     "area_pct": round(100.0 * n / L.size, 2)})
    inks.sort(key=lambda x: -x["pixels"])
    inks = inks[:MAX_INKS]
    names: dict = {}
    out = []
    for i, k_ in enumerate(inks, 1):
        name = colour_name(k_["centre"])
        names[name] = names.get(name, 0) + 1
        out.append({"id": f"I{i}", "name": name if names[name] == 1 else f"{name} {names[name]}",
                    "box": k_["box"], "area_pct": k_["area_pct"], "points": k_["points"]})
    if not out:
        raise ColourError("No ink area was large enough to measure. Scan at 300 dpi or more.")
    return out


def measure(rgb: np.ndarray, dpi: float, points: list) -> dict | None:
    """Median L*a*b* at the sample points, after descreening; outlier points (misregistration, edges) dropped."""
    img = descreen(rgb, dpi)
    h, w = img.shape[:2]
    vals = [img[y, x] for x, y in points if 0 <= x < w and 0 <= y < h]
    if len(vals) < 10:
        return None
    lab = srgb_to_lab(np.array(vals, float))
    med = np.median(lab, axis=0)
    dist = np.sqrt(((lab - med) ** 2).sum(1))
    mad = np.median(dist) + 1e-6
    keep = lab[dist <= max(3.0 * mad, 2.0)]
    if len(keep) < 8:
        keep = lab
    m = np.median(keep, axis=0)
    out = lab_dict(m)
    out["n"] = int(len(keep))
    out["spread"] = round(float(np.median(np.sqrt(((keep - m) ** 2).sum(1)))), 2)
    return out


# ----------------------------------------------------------------------------------------------- shade verification
def verify_ink(std: dict, light: dict, dark: dict) -> tuple[str, str]:
    s, l, d = lab_vec(std), lab_vec(light), lab_vec(dark)
    e_l, e_d = de00(s, l), de00(s, d)
    if e_l < MIN_SHADE_DE and e_d < MIN_SHADE_DE:
        return "flat", "Light and Dark do not differ from the Standard for this ink; it is checked against the Standard only."
    light_ok = l[0] >= s[0] - ORDER_MARGIN_L
    dark_ok = d[0] <= s[0] + ORDER_MARGIN_L
    if l[0] < s[0] - 1.0 and d[0] > s[0] + 1.0:
        return "swapped", (f"The Light card is darker (L* {l[0]:.1f}) and the Dark card lighter (L* {d[0]:.1f}) than the "
                           f"Standard (L* {s[0]:.1f}): the Light and Dark cards look swapped.")
    if not light_ok:
        return "outside", f"The Light card is darker than the Standard for this ink (L* {l[0]:.1f} vs {s[0]:.1f})."
    if not dark_ok:
        return "outside", f"The Dark card is lighter than the Standard for this ink (L* {d[0]:.1f} vs {s[0]:.1f})."
    if e_l < MIN_SHADE_DE:
        return "one_sided", "The Light card does not differ from the Standard for this ink."
    if e_d < MIN_SHADE_DE:
        return "one_sided", "The Dark card does not differ from the Standard for this ink."
    return "ok", f"Light ΔE00 {e_l:.1f} lighter, Dark ΔE00 {e_d:.1f} darker than the Standard."


def verify_set(inks: list[dict]) -> tuple[str, list[str]]:
    msgs = []
    statuses = [i["status"] for i in inks]
    controlled = [s for s in statuses if s != "flat"]
    if not controlled:
        return "fail", ["None of the inks differs between Light, Standard and Dark. Check that three different cards were "
                        "scanned."]
    swapped = statuses.count("swapped")
    if swapped and swapped >= len(controlled) / 2:
        msgs.append("For most inks the Light and Dark cards look swapped. Check the labels on the cards.")
        return "fail", msgs
    if any(s in ("swapped", "outside") for s in statuses):
        bad = [i["name"] for i in inks if i["status"] in ("swapped", "outside")]
        msgs.append("The Standard is not between Light and Dark for: " + ", ".join(bad) + ".")
        return "fail", msgs
    if "one_sided" in statuses:
        msgs.append("Some inks differ on one side only; those limits are one-sided.")
        return "warn", msgs
    return "pass", ["Light is lighter and Dark darker than the Standard for every shade-controlled ink."]


def analyse_set(source: str, std_path: str | None, light_path: str | None, dark_path: str | None,
                spectro: dict | None = None) -> dict:
    """Build the measurement record of a shade set. spectro: {"standard": {name: lab}, "light": ..., "dark": ...}"""
    result = {"engine": COLOUR_VERSION, "source": source, "confidence": CONFIDENCE.get(source, "relative"),
              "inks": [], "alignment": {}, "calibration": {}}
    if source == "spectro":
        names = [n for n in spectro["standard"] if n in spectro["light"] and n in spectro["dark"]]
        if not names:
            raise ColourError("The three measurement files have no patch names in common.")
        for i, n in enumerate(names, 1):
            ink = {"id": f"I{i}", "name": n, "points": [], "box": [], "area_pct": None,
                   "standard": lab_dict(spectro["standard"][n]), "light": lab_dict(spectro["light"][n]),
                   "dark": lab_dict(spectro["dark"][n])}
            ink["status"], ink["note"] = verify_ink(ink["standard"], ink["light"], ink["dark"])
            result["inks"].append(ink)
        result["verification"], result["messages"] = verify_set(result["inks"])
        return result
    std, dpi = load_image(std_path)
    std_c, cal = calibrate(std, source)
    result["calibration"]["standard"] = cal
    result["size"] = [int(std.shape[1]), int(std.shape[0])]
    result["dpi"] = dpi
    inks = find_inks(std_c, dpi)
    imgs = {"standard": std_c}
    for tag, path in (("light", light_path), ("dark", dark_path)):
        img, _ = load_image(path)
        warped, info = align(img, std)
        if not info["ok"]:
            raise ColourError(f"The {tag.title()} scan could not be aligned with the Standard. Scan the same artwork, "
                              "the whole card, the right way up.")
        result["alignment"][tag] = info
        imgs[tag], result["calibration"][tag] = calibrate(warped, source)
    for ink in inks:
        for tag in ("standard", "light", "dark"):
            m = measure(imgs[tag], dpi, ink["points"])
            if m is None:
                raise ColourError(f"{ink['name']} could not be measured on the {tag} scan.")
            ink[tag] = m
        ink["status"], ink["note"] = verify_ink(ink["standard"], ink["light"], ink["dark"])
    result["inks"] = inks
    result["verification"], result["messages"] = verify_set(inks)
    result["_images"] = imgs            # not stored; used to write previews
    return result


# ----------------------------------------------------------------------------------------------- sample evaluation
def _closest_on_path(p: np.ndarray, path: list[np.ndarray]) -> tuple[float, float, int, float]:
    """Closest point of p on the polyline Dark -> Standard -> Light.
    Returns (distance, position 0..2, segment, unclamped t on the end segment)."""
    best = None
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ab = b - a
        L2 = float(ab @ ab)
        t_raw = float((p - a) @ ab / L2) if L2 > 1e-9 else 0.0
        t = min(1.0, max(0.0, t_raw))
        q = a + t * ab
        dist = float(np.linalg.norm(p - q))
        if best is None or dist < best[0]:
            best = (dist, i + t, i, t_raw)
    return best


def evaluate_ink(sample: dict, ink: dict, tolerance: float, flat_tolerance: float) -> dict:
    s = lab_vec(sample)
    S, Lt, D = lab_vec(ink["standard"]), lab_vec(ink["light"]), lab_vec(ink["dark"])
    out = {"de_standard": round(de00(s, S), 2), "de_light": round(de00(s, Lt), 2), "de_dark": round(de00(s, D), 2),
           "dL": round(float(s[0] - S[0]), 2), "da": round(float(s[1] - S[1]), 2), "db": round(float(s[2] - S[2]), 2)}
    if ink.get("status") == "flat":
        ok = out["de_standard"] <= flat_tolerance
        out.update(verdict="pass" if ok else "fail", position="standard only",
                   reason=(f"ΔE00 {out['de_standard']} to the Standard (tolerance {flat_tolerance})."))
        out["advice"] = [] if ok else advice(s, S)
        return out
    dist, pos, seg, t_raw = _closest_on_path(s, [D, S, Lt])
    out["off_path"] = round(dist, 2)
    out["position"] = round(pos, 3)              # 0 = Dark, 1 = Standard, 2 = Light
    beyond = None
    if seg == 0 and t_raw < 0:
        beyond = "dark"
    elif seg == 1 and t_raw > 1:
        beyond = "light"
    margin = 0.5                                  # ΔE allowance past the end cards (measurement noise)
    if beyond:
        # distance to the end segment's extension: "darker than Dark" when the sample continues the shade direction
        a, b = (D, S) if beyond == "dark" else (S, Lt)
        ab = b - a
        q = a + t_raw * ab
        ext_off = float(np.linalg.norm(s - q))
        if ext_off > max(tolerance, 0.35 * float(np.linalg.norm(s - (D if beyond == "dark" else Lt)))):
            beyond = None                          # not along the shade direction: a hue/chroma problem
            dist = max(dist, ext_off)
    if dist > tolerance and not beyond:
        # Off the Dark-Light range: the hue or chroma differs, whatever the lightness.
        out.update(verdict="fail", where=f"outside the Dark–Light range by ΔE {dist:.1f} (hue or chroma differs)",
                   reason=f"Sample is {dist:.1f} ΔE away from the Dark–Standard–Light range; ΔE00 to Standard "
                          f"{out['de_standard']}.", advice=advice(s, S))
        return out
    if beyond == "dark":
        over = float(np.linalg.norm(s - D))
        ok = over <= margin
        where = f"darker than the Dark limit (ΔE00 {out['de_dark']} beyond it)"
        ref = D
    elif beyond == "light":
        over = float(np.linalg.norm(s - Lt))
        ok = over <= margin
        where = f"lighter than the Light limit (ΔE00 {out['de_light']} beyond it)"
        ref = Lt
    else:
        ok = dist <= tolerance
        if pos < 1:
            where = f"between Dark and Standard ({round((1 - pos) * 100)}% of the way to Dark)"
        else:
            where = f"between Standard and Light ({round((pos - 1) * 100)}% of the way to Light)"
        ref = S
    if not ok and not beyond:
        where += f", but {dist:.1f} ΔE off the Dark–Light range in hue or chroma"
    out.update(verdict="pass" if ok else "fail", where=where,
               reason=f"Sample is {where}; ΔE00 to Standard {out['de_standard']}.")
    out["advice"] = [] if ok else advice(s, ref if beyond else S)
    return out


def advice(sample: np.ndarray, target: np.ndarray) -> list[str]:
    """Plain, directional hints for the printer. Advisory only - never an ink recipe."""
    dL, da, db = (float(x) for x in sample - target)
    C1, C0 = math.hypot(sample[1], sample[2]), math.hypot(target[1], target[2])
    tips = []
    if dL < -1.0:
        tips.append(f"Too dark (ΔL* {dL:+.1f}): reduce ink density / film weight.")
    elif dL > 1.0:
        tips.append(f"Too light (ΔL* {dL:+.1f}): increase ink density / film weight.")
    if da > 1.5:
        tips.append(f"Too red (Δa* {da:+.1f}): less magenta, or a touch more cyan.")
    elif da < -1.5:
        tips.append(f"Too green (Δa* {da:+.1f}): more magenta, or less cyan.")
    if db > 1.5:
        tips.append(f"Too yellow (Δb* {db:+.1f}): less yellow.")
    elif db < -1.5:
        tips.append(f"Too blue (Δb* {db:+.1f}): more yellow, or less cyan.")
    if C1 - C0 < -2.0:
        tips.append(f"Duller than the target (ΔC* {C1 - C0:+.1f}): check ink strength and contamination.")
    elif C1 - C0 > 2.0:
        tips.append(f"More saturated than the target (ΔC* {C1 - C0:+.1f}).")
    return tips or ["Small difference; check the measurement before adjusting the press."]


def check_sample(measurement: dict, std_path: str | None, sample_path: str | None, sample_source: str,
                 tolerance: float, flat_tolerance: float, spectro_sample: dict | None = None) -> dict:
    """Measure a sample at the shade set's points and judge every ink."""
    out = {"engine": COLOUR_VERSION, "source": sample_source, "confidence": CONFIDENCE.get(sample_source, "relative"),
           "set_confidence": measurement.get("confidence"), "inks": [], "tolerance": tolerance,
           "flat_tolerance": flat_tolerance}
    images = None
    if spectro_sample is None:
        img, dpi = load_image(sample_path)
        std_img, _ = load_image(std_path)
        warped, info = align(img, std_img)
        out["alignment"] = info
        if not info["ok"]:
            raise ColourError("The sample could not be aligned with the Standard scan; scan the same artwork, whole, "
                              "the right way up.")
        cal_img, out["calibration"] = calibrate(warped, sample_source)
        images = {"sample": cal_img, "aligned": warped}
        dpi = measurement.get("dpi", dpi)
    for ink in measurement["inks"]:
        if spectro_sample is not None:
            lab = spectro_sample.get(ink["name"])
            m = lab_dict(lab) if lab is not None else None
        else:
            m = measure(images["sample"], dpi, ink["points"])
        row = {"id": ink["id"], "name": ink["name"], "status": ink.get("status"), "standard": ink["standard"],
               "light": ink["light"], "dark": ink["dark"], "box": ink.get("box"), "sample": m}
        if m is None:
            row.update(verdict="not_measured", reason="This ink could not be measured on the sample.")
        else:
            row.update(evaluate_ink(m, ink, tolerance, flat_tolerance))
            if out["confidence"] == "screening" and row["verdict"] in ("pass", "fail"):
                row["screen_verdict"] = row["verdict"]
                row["verdict"] = "screen"
        out["inks"].append(row)
    v = [r["verdict"] for r in out["inks"]]
    out["verdict"] = ("fail" if "fail" in v else "screen" if "screen" in v else
                      "incomplete" if "not_measured" in v else "pass")
    if images:
        out["_images"] = images
    return out


# ----------------------------------------------------------------------------------------------- spectro files
def parse_spectro(data: bytes) -> dict[str, np.ndarray]:
    """CxF3 (XML) or CGATS / IT8 text: {patch name: L*a*b*}."""
    text = data.decode("utf-8", "replace")
    if "<" in text[:200] and ("cc:CxF" in text or "CxF" in text[:2000]):
        return _parse_cxf(text)
    return _parse_cgats(text)


def _parse_cgats(text: str) -> dict:
    lines = text.splitlines()
    fmt, rows, mode = [], [], None
    for ln in lines:
        s = ln.strip()
        if s.upper() == "BEGIN_DATA_FORMAT":
            mode = "fmt"
            continue
        if s.upper() == "END_DATA_FORMAT":
            mode = None
            continue
        if s.upper() == "BEGIN_DATA":
            mode = "data"
            continue
        if s.upper() == "END_DATA":
            mode = None
            continue
        if mode == "fmt":
            fmt += s.split()
        elif mode == "data" and s:
            rows.append(re.findall(r'"[^"]*"|\S+', s))
    up = [f.upper() for f in fmt]
    try:
        iL, ia, ib = up.index("LAB_L"), up.index("LAB_A"), up.index("LAB_B")
    except ValueError:
        raise ColourError("The CGATS file has no LAB_L, LAB_A, LAB_B columns.")
    iname = next((up.index(k) for k in ("SAMPLE_NAME", "SAMPLE_ID", "PATCH") if k in up), 0)
    out = {}
    for r in rows:
        if len(r) <= max(iL, ia, ib, iname):
            continue
        name = r[iname].strip('"')
        try:
            out[name] = np.array([float(r[iL]), float(r[ia]), float(r[ib])])
        except ValueError:
            continue
    if not out:
        raise ColourError("No measurements were found in the CGATS file.")
    return out


def _parse_cxf(text: str) -> dict:
    root = ET.fromstring(text)
    out = {}
    for obj in root.iter():
        if not obj.tag.endswith("Object"):
            continue
        name = obj.attrib.get("Name") or obj.attrib.get("Id")
        for el in obj.iter():
            if el.tag.endswith("ColorCIELab"):
                vals = {c.tag.split("}")[-1]: c.text for c in el}
                try:
                    out[name] = np.array([float(vals["L"]), float(vals["A"]), float(vals["B"])])
                except (KeyError, TypeError, ValueError):
                    pass
                break
    if not out:
        raise ColourError("No L*a*b* measurements were found in the CxF file.")
    return out


# ----------------------------------------------------------------------------------------------- pictures
def swatch_strip(cells: list[tuple[str, dict | None]], height: int = 120, width: int = 150) -> Image.Image:
    """Side-by-side colour patches with labels, e.g. Dark | Standard | Light | Sample."""
    from PIL import ImageDraw
    from skimage.color import lab2rgb
    im = Image.new("RGB", (width * len(cells), height + 34), "white")
    d = ImageDraw.Draw(im)
    for i, (label, lab) in enumerate(cells):
        if lab:
            rgb = lab2rgb(np.array([[[lab["L"], lab["a"], lab["b"]]]], float))[0, 0]
            col = tuple(int(round(c * 255)) for c in rgb)
            d.rectangle([i * width + 4, 4, (i + 1) * width - 4, height], fill=col, outline=(120, 120, 120))
        else:
            d.rectangle([i * width + 4, 4, (i + 1) * width - 4, height], outline=(160, 160, 160))
            d.line([i * width + 4, 4, (i + 1) * width - 4, height], fill=(160, 160, 160))
        d.text((i * width + 8, height + 8), label, fill=(30, 30, 30))
    return im


def outline_inks(rgb: np.ndarray, inks: list[dict], max_side: int = 1600) -> Image.Image:
    """Preview of a scan with each ink's main area outlined and labelled."""
    from PIL import ImageDraw
    im = Image.fromarray(rgb)
    f = min(1.0, max_side / max(im.size))
    im = im.resize((int(im.width * f), int(im.height * f)))
    d = ImageDraw.Draw(im)
    for ink in inks:
        if not ink.get("box"):
            continue
        x0, y0, x1, y1 = (int(v * f) for v in ink["box"])
        d.rectangle([x0, y0, x1, y1], outline=(200, 16, 46), width=3)
        d.rectangle([x0, max(0, y0 - 18), x0 + 9 * len(ink["id"]) + 10, y0], fill=(200, 16, 46))
        d.text((x0 + 4, max(0, y0 - 16)), ink["id"], fill="white")
    return im


def to_jpeg(im: Image.Image, q: int = 85) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return buf.getvalue()
