"""PDF report and Excel findings log, built from result.json + reviewer decisions."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

STEP_NAMES = {1: "Step 1 — Approved leaflet audit", 2: "Step 2 — Content comparison",
              3: "Step 3 — Punctuation & typography"}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font_path():
    for p in (os.environ.get("REPORT_FONT", ""), FONT,
              "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"):
        if p and os.path.exists(p):
            return p
    return None


def text_image(text: str, width_px: int = 900, size: int = 22) -> Image.Image:
    """Render (possibly Arabic, RTL) text to an image — ReportLab cannot shape Arabic."""
    fp = _font_path()
    font = ImageFont.truetype(fp, size, layout_engine=ImageFont.Layout.RAQM) if fp else ImageFont.load_default()
    rtl = any("؀" <= c <= "ۿ" for c in text)
    words, lines, cur = text.split(), [], ""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for w in words:
        t = (cur + " " + w).strip()
        if probe.textlength(t, font=font, direction="rtl" if rtl else None) > width_px - 20 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    lines = lines[:12] or [""]
    h = int(size * 1.5) * len(lines) + 10
    img = Image.new("RGB", (width_px, h), "white")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        y = 5 + i * int(size * 1.5)
        if rtl:
            wln = d.textlength(ln, font=font, direction="rtl")
            d.text((width_px - 10 - wln, y), ln, font=font, fill="black", direction="rtl")
        else:
            d.text((10, y), ln, font=font, fill="black")
    return img


def excel(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Findings"
    head = ["ID", "Step", "Lang", "Severity", "Type", "Finding", "Section", "Category", "Approved location",
            "Design location", "What changed", "Action", "Approved text", "Design text",
            "AI verdict", "AI note", "Reviewer decision", "Reviewer comment", "Reviewed by", "Reviewed at",
            "Approved screenshot", "Design screenshot"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
    fills = {"critical": "FDE2E2", "major": "FDEBD8", "minor": "FEF6D8", "info": "E3EDFB"}
    for i, f in enumerate(result["findings"], start=2):
        dec = decisions.get(f["id"], {})
        ai = f.get("ai") or {}
        ws.append([f["id"], f["step"], f["lang"], f["severity"], f["kind"], f["title"],
                   f.get("section", ""), f.get("category", ""), f.get("where_ref", ""), f.get("where_des", ""),
                   f.get("explanation", ""), f.get("action", ""), f["ref_text"], f["des_text"], ai.get("verdict", ""), ai.get("explanation", f.get("note", "")),
                   dec.get("decision", "pending"), dec.get("comment", ""), dec.get("user", ""), dec.get("at", "")])
        for c in ws[i]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(i, 4).fill = PatternFill("solid", fgColor=fills.get(f["severity"], "FFFFFF"))
        ws.row_dimensions[i].height = 90
        for col, tag in ((21, "approved"), (22, "design")):
            p = os.path.join(shots_dir, f"{f['id']}_{tag}.jpg")
            if os.path.exists(p) and f["severity"] != "info":
                im = Image.open(p).convert("RGB")
                im.thumbnail((320, 115))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                buf.seek(0)
                x = XLImage(buf)
                ws.add_image(x, ws.cell(i, col).coordinate)
    widths = [7, 6, 6, 9, 11, 34, 26, 18, 18, 18, 50, 40, 36, 36, 14, 36, 14, 30, 16, 18, 46, 46]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = "A2"
    info = wb.create_sheet("Audit info")
    for k, v in meta.items():
        info.append([k, str(v)])
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 90
    wb.save(path)


def pdf(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict, signatures: list):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    ss = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10)
    h1, h2 = ss["Title"], ss["Heading2"]
    sevcol = {"critical": colors.HexColor("#DC2626"), "major": colors.HexColor("#EA580C"),
              "minor": colors.HexColor("#CA8A04"), "info": colors.HexColor("#2563EB")}
    W = A4[0] - 30 * mm

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.drawString(15 * mm, 8 * mm, f"Leaflet Audit {meta.get('Audit ID', '')} · {meta.get('Product', '')} · "
                                      f"engine {result['engine_version']}")
        c.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    def img_flow(p, max_w, max_h=70 * mm):
        if not p or not os.path.exists(p):
            return Paragraph("<i>no screenshot</i>", small)
        im = Image.open(p).convert("RGB")
        r = min(max_w / im.width, max_h / im.height, 1.0 * mm * 0.22)
        im.thumbnail((1100, 1100))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        buf.seek(0)
        w0, h0 = Image.open(p).size
        return RLImage(buf, w0 * r, h0 * r)

    def txt_flow(t, w):
        if any("؀" <= c <= "ۿ" for c in t):
            im = text_image(t, 900, 22)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            buf.seek(0)
            r = w / im.width
            return RLImage(buf, im.width * r, im.height * r)
        from xml.sax.saxutils import escape
        return Paragraph(escape(t[:700]) or "—", small)

    story = [Paragraph("Leaflet Compliance Audit Report", h1)]
    rows = [[k, Paragraph(str(v), small)] for k, v in meta.items()]
    t = Table(rows, colWidths=[45 * mm, W - 45 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 6 * mm)]

    # summary
    summ = [["Step", "Critical", "Major", "Minor", "Info", "Accepted", "Rejected", "Pending"]]
    for s in (1, 2, 3):
        fs = [f for f in result["findings"] if f["step"] == s]
        cnt = lambda sev: sum(f["severity"] == sev for f in fs)
        dec = lambda d: sum(decisions.get(f["id"], {}).get("decision", "pending") == d for f in fs)
        summ.append([STEP_NAMES[s], cnt("critical"), cnt("major"), cnt("minor"), cnt("info"),
                     dec("confirmed"), dec("rejected"), dec("pending")])
    t = Table(summ, colWidths=[62 * mm] + [(W - 62 * mm) / 7] * 7)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    story += [Paragraph("Summary", h2), t, Spacer(1, 4 * mm)]

    if signatures:
        srows = [["Meaning", "Name", "Date/time (UTC)", "Statement"]]
        for s in signatures:
            srows.append([s["meaning"], s["user_name"], s["at"], Paragraph(s.get("statement", ""), small)])
        t = Table(srows, colWidths=[28 * mm, 40 * mm, 38 * mm, W - 106 * mm])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
        story += [Paragraph("Electronic signatures", h2), t]

    show_info = meta.get("_include_info", False)
    for s in (1, 2, 3):
        fs = [f for f in result["findings"] if f["step"] == s and (show_info or f["severity"] != "info"
              or decisions.get(f["id"], {}).get("decision") == "confirmed")]
        story += [PageBreak(), Paragraph(STEP_NAMES[s], h2)]
        if not fs:
            story.append(Paragraph("No findings.", ss["Normal"]))
        for f in fs:
            dec = decisions.get(f["id"], {})
            ai = f.get("ai") or {}
            hdr = Table([[f["id"], f["severity"].upper(), Paragraph(f["title"], small),
                          dec.get("decision", "pending")]],
                        colWidths=[14 * mm, 20 * mm, W - 64 * mm, 30 * mm])
            hdr.setStyle(TableStyle([("BACKGROUND", (1, 0), (1, 0), sevcol.get(f["severity"], colors.grey)),
                                     ("TEXTCOLOR", (1, 0), (1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                     ("BOX", (0, 0), (-1, -1), 0.4, colors.grey)]))
            half = (W - 4 * mm) / 2
            if s == 1:
                body = [[img_flow(os.path.join(shots_dir, f"{f['id']}_approved.jpg"), W - 4 * mm)],
                        [txt_flow(f["ref_text"], W - 4 * mm)]]
                bt = Table(body, colWidths=[W])
                bt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
            body = [[Paragraph("<b>Approved</b>", small), Paragraph("<b>Design</b>", small)],
                    [img_flow(os.path.join(shots_dir, f"{f['id']}_approved.jpg"), half),
                     img_flow(os.path.join(shots_dir, f"{f['id']}_design.jpg"), half)],
                    [txt_flow(f["ref_text"], half), txt_flow(f["des_text"], half)]]
            if s != 1:
                bt = Table(body, colWidths=[half, half])
                bt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
            notes = []
            if f.get("section") or f.get("where_ref"):
                notes.append(" · ".join(x for x in (f.get("section"), f.get("category"),
                                                    f.get("where_ref") and "Approved: " + f["where_ref"],
                                                    f.get("where_des") and "Design: " + f["where_des"]) if x))
            if f.get("explanation"):
                notes.append("What changed: " + f["explanation"])
            if f.get("action"):
                notes.append("Action: " + f["action"])
            if ai.get("explanation"):
                notes.append(f"AI ({ai.get('verdict', '')}): {ai['explanation']}")
            if f.get("note"):
                notes.append(f["note"])
            if dec.get("comment"):
                notes.append(f"Reviewer ({dec.get('user', '')}): {dec['comment']}")
            from xml.sax.saxutils import escape
            block = [hdr, bt] + [Paragraph(escape(n), small) for n in notes] + [Spacer(1, 4 * mm)]
            story.append(KeepTogether(block))
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title="Leaflet Audit Report")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def standalone_images(result: dict, shots_dir: str, page_px: int = 1500) -> dict:
    """All screenshots and page previews as data URIs, so the HTML report works offline."""
    import base64
    out = {}

    def enc(path, max_px, q):
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    for f in result["findings"]:
        for tag in ("approved", "design"):
            p = os.path.join(shots_dir, f"{f['id']}_{tag}.jpg")
            if os.path.exists(p):
                out[f"{f['id']}_{tag}.jpg"] = enc(p, 1000, 72 if f["severity"] != "info" else 55)
    for tag in ("approved", "design"):
        n = result[tag]["pages"]
        for i in range(n):
            p = os.path.join(shots_dir, f"{tag}_p{i}.jpg")
            if os.path.exists(p):
                out[f"{tag}_p{i}.jpg"] = enc(p, page_px if tag == "approved" else 2400, 70)
    return out


def html_report(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict, signatures: list):
    """Self-contained interactive report (one HTML file with embedded images) to send to people
    who have no Comproof account. Decisions and signatures are shown, not editable."""
    import jinja2
    tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tpl_dir), autoescape=True)
    data = {
        "mode": "file", "lang": "en", "findings": result["findings"], "exclusions": result["exclusions"],
        "decisions": {k: {"decision": v["decision"], "comment": v.get("comment"), "user": v.get("user"), "at": v.get("at")}
                      for k, v in decisions.items()},
        "sizes": {"approved": result["approved"]["sizes"], "design": result["design"]["sizes"]},
        "images": standalone_images(result, shots_dir), "imgBase": "", "canDecide": False, "decideUrl": "", "csrf": "",
    }
    html = env.get_template("report.html").render(mode="file", lang="en", meta=meta, sigs=signatures, urls={},
                                                  can_sign=False, data=data)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
