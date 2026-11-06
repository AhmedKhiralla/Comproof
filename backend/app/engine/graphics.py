"""Graphics and layout: overlay the test on the approved artwork and find graphic elements that are missing,
added or changed (logos, pictograms, symbols, lines). Text areas are masked out because the text levels already
compare every word. Only meaningful when both files show the same layout (artwork vs proof, artwork vs scan of the
printed item); when the pages cannot be aligned the check is skipped with a note."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def _line_boxes(regions, page: int) -> list[list[float]]:
    return [ln.box for r in regions if r.page == page for ln in r.lines]


def _warp_boxes(boxes, H) -> list[list[float]]:
    import cv2
    if H is None or not boxes:
        return boxes
    out = []
    H = np.asarray(H, float)
    for x0, y0, x1, y1 in boxes:
        pts = np.float32([[x0, y0], [x1, y0], [x0, y1], [x1, y1]]).reshape(-1, 1, 2)
        q = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
        out.append([float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())])
    return out


def compare(ref_doc, des_doc, ref_regions, des_regions, min_mm: float = 2.5) -> tuple[list[dict], list[str]]:
    """Returns (differences, notes). A difference: page, box (approved pixels), kind, area_mm2, severity,
    and the two crops as PIL images."""
    import cv2
    from .colour import align, paper_white, normalise_white
    diffs, notes = [], []
    for i in range(min(len(ref_doc.pages), len(des_doc.pages))):
        rp, dp = ref_doc.pages[i], des_doc.pages[i]
        ref = np.asarray(rp.image.convert("RGB"))
        des = np.asarray(dp.image.convert("RGB"))
        warped, info = align(des, ref)
        if not info.get("ok") or info.get("method") != "features" or info.get("inlier_ratio", 0) < 0.35:
            notes.append(f"Page {i + 1}: the test page could not be overlaid on the approved page (different layout), "
                         "so graphics were not compared.")
            continue
        dpi = rp.source_dpi if rp.source_dpi and rp.source_dpi > 72 else 300.0
        px_mm = dpi / 25.4
        a = normalise_white(ref, paper_white(ref))
        b = normalise_white(warped, paper_white(warped))
        sigma = max(1.0, 0.25 * px_mm)
        ga = cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), (0, 0), sigma).astype(np.int16)
        gb = cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_RGB2GRAY), (0, 0), sigma).astype(np.int16)
        # colour differences matter too (a logo printed in the wrong colour)
        ca = cv2.GaussianBlur(a, (0, 0), sigma).astype(np.int16)
        cb = cv2.GaussianBlur(b, (0, 0), sigma).astype(np.int16)
        diff = np.maximum(np.abs(ga - gb), np.abs(ca - cb).max(-1) // 2).astype(np.uint8)
        mask = (diff > 45).astype(np.uint8)
        # mask the text: approved line boxes, and the test's line boxes moved into approved coordinates
        H = info.get("H")
        boxes = _line_boxes(ref_regions, i) + _warp_boxes(_line_boxes(des_regions, i), H)
        pad = int(0.6 * px_mm)
        for x0, y0, x1, y1 in boxes:
            mask[max(0, int(y0) - pad):int(y1) + pad, max(0, int(x0) - pad):int(x1) + pad] = 0
        # warped borders (outside the test image) are not differences
        valid = cv2.warpPerspective(np.ones(des.shape[:2], np.uint8), np.asarray(H, float), (ref.shape[1], ref.shape[0])) \
            if H is not None else np.ones(mask.shape, np.uint8)
        mask &= cv2.erode(valid, np.ones((int(px_mm * 2) | 1, int(px_mm * 2) | 1), np.uint8))
        k = max(3, int(px_mm * 0.8)) | 1
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
        min_px = (min_mm * px_mm) ** 2
        for j in range(1, n):
            x, y, w, h, area = stats[j]
            if area < min_px:
                continue
            ink_a = float((ga[y:y + h, x:x + w] < 200).mean())
            ink_b = float((gb[y:y + h, x:x + w] < 200).mean())
            if ink_a > 0.08 and ink_b < 0.25 * ink_a:
                kind, title = "missing", "Graphic element missing on the test"
            elif ink_b > 0.08 and ink_a < 0.25 * ink_b:
                kind, title = "added", "Graphic element added on the test"
            else:
                kind, title = "changed", "Graphic element changed"
            area_mm2 = area / px_mm ** 2
            m = int(3 * px_mm)
            box = [max(0, x - m), max(0, y - m), min(ref.shape[1], x + w + m), min(ref.shape[0], y + h + m)]
            crop_a = Image.fromarray(a[box[1]:box[3], box[0]:box[2]])
            crop_b = Image.fromarray(b[box[1]:box[3], box[0]:box[2]])
            for im, col in ((crop_a, (200, 16, 46)), (crop_b, (29, 95, 168))):
                ImageDraw.Draw(im).rectangle([x - box[0], y - box[1], x - box[0] + w, y - box[1] + h],
                                             outline=col, width=max(2, int(px_mm * 0.3)))
            diffs.append({"page": i, "box": [int(x), int(y), int(x + w), int(y + h)], "kind": kind, "title": title,
                          "area_mm2": float(round(area_mm2, 1)), "severity": "major" if area_mm2 >= 40 else "minor",
                          "crop_ref": crop_a, "crop_des": crop_b})
        if len(diffs) > 60:
            notes.append("More than 60 graphic differences: the files may not be the same artwork version.")
            diffs = sorted(diffs, key=lambda d: -d["area_mm2"])[:60]
            break
    return diffs, notes
