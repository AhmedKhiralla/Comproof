"""PDF report and Excel findings log, built from result.json + reviewer decisions."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

from . import messages

STEP_NAMES = messages.STEP_NAMES_L["en"]


def _steps(result: dict) -> list[int]:
    present = {f["step"] for f in result["findings"]} | {1, 2, 3}
    for key, step in (("colour", 4), ("barcodes", 5), ("graphics", 6), ("print", 7)):
        if key in (result.get("checks") or {}):
            present.add(step)
    return sorted(present)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font_path():
    for p in (os.environ.get("REPORT_FONT", ""), FONT,
              "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
              "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"):
        if p and os.path.exists(p):
            return p
    return None


def _first_strong_rtl(text: str) -> bool:
    for c in text:
        if "\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f" or "\ufb50" <= c <= "\ufeff":
            return True
        if c.isalpha():
            return False
    return False


def has_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06ff" for c in text or "")


def text_image(text: str, width_px: int = 900, size: int = 22, max_lines: int = 12) -> Image.Image:
    """Render text that contains Arabic to an image. ReportLab cannot shape Arabic, so mixed English/Arabic
    lines are laid out by libraqm (bidi + shaping); the paragraph direction follows its first strong letter."""
    fp = _font_path()
    font = ImageFont.truetype(fp, size, layout_engine=ImageFont.Layout.RAQM) if fp else ImageFont.load_default()
    rtl = _first_strong_rtl(text)
    direction = "rtl" if rtl else "ltr"
    words, lines, cur = text.split(), [], ""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for w in words:
        t = (cur + " " + w).strip()
        if probe.textlength(t, font=font, direction=direction) > width_px - 20 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] += " …"
    lines = lines or [""]
    h = int(size * 1.5) * len(lines) + 10
    img = Image.new("RGB", (width_px, h), "white")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        y = 5 + i * int(size * 1.5)
        if rtl:
            wln = d.textlength(ln, font=font, direction="rtl")
            d.text((width_px - 10 - wln, y), ln, font=font, fill="black", direction="rtl")
        else:
            d.text((10, y), ln, font=font, fill="black", direction="ltr")
    return img


def _rl_fonts() -> tuple[str, str]:
    """A Unicode TrueType font for the PDF (accents, →, Δ, ≤, « »); Helvetica when none is installed."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "CP-Sans" in pdfmetrics.getRegisteredFontNames():
        return "CP-Sans", "CP-Sans-Bold"
    reg = FONT
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not os.path.exists(reg):
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("CP-Sans", reg))
    pdfmetrics.registerFont(TTFont("CP-Sans-Bold", bold if os.path.exists(bold) else reg))
    from reportlab.lib.fonts import addMapping
    addMapping("CP-Sans", 0, 0, "CP-Sans"); addMapping("CP-Sans", 1, 0, "CP-Sans-Bold")
    addMapping("CP-Sans", 0, 1, "CP-Sans"); addMapping("CP-Sans", 1, 1, "CP-Sans-Bold")
    return "CP-Sans", "CP-Sans-Bold"


def excel(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict, lang: str = "en"):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill

    L = messages.L.get(lang, messages.L["en"])
    findings = messages.localize_findings(result["findings"], lang)
    sev_l = {"critical": L["critical"], "major": L["major"], "minor": L["minor"], "info": L["info"]}
    wb = Workbook()
    ws = wb.active
    ws.title = L["findings"]
    if lang == "ar":
        ws.sheet_view.rightToLeft = True
    ws.append(L["xl_head"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
    fills = {"critical": "FDE2E2", "major": "FDEBD8", "minor": "FEF6D8", "info": "E3EDFB"}
    for i, f in enumerate(findings, start=2):
        dec = decisions.get(f["id"], {})
        ai = f.get("ai") or {}
        lang_names = messages.HTML_LABELS.get(lang, messages.HTML_LABELS["en"])["langs"]
        aiv = messages.HTML_LABELS.get(lang, messages.HTML_LABELS["en"])["aiv"]
        ws.append([f["id"], f["step"], lang_names.get(f["lang"], f["lang"]), sev_l.get(f["severity"], f["severity"]),
                   f["kind"], f["title"], f.get("section") or "", f.get("category") or "", f.get("where_ref") or "",
                   f.get("where_des") or "", f.get("explanation") or "", f.get("action") or "", f.get("ref_text") or "",
                   f.get("des_text") or "", aiv.get(ai.get("verdict") or "", ai.get("verdict") or ""),
                   ai.get("explanation") or f.get("note") or "",
                   L["st"].get(dec.get("decision", "pending"), dec.get("decision", "pending")),
                   dec.get("comment", ""), dec.get("user", ""), dec.get("at", "")])
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
    info = wb.create_sheet(L["audit_info"])
    if lang == "ar":
        info.sheet_view.rightToLeft = True
    for k, v in meta.items():
        info.append([messages.meta_key(k, lang), str(v)])
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 90
    wb.save(path)


def pdf(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict, signatures: list, lang: str = "en"):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    ss = getSampleStyleSheet()
    body_font, bold_font = _rl_fonts()
    for k in ("Normal", "Title", "Heading2"):
        ss[k].fontName = bold_font if k != "Normal" else body_font
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10, fontName=body_font)
    h1, h2 = ss["Title"], ss["Heading2"]
    L = messages.L.get(lang, messages.L["en"])
    step_names = messages.STEP_NAMES_L.get(lang, STEP_NAMES)
    sev_l = {"critical": L["critical"], "major": L["major"], "minor": L["minor"], "info": L["info"]}
    result = dict(result, findings=messages.localize_findings(result["findings"], lang))
    sevcol = {"critical": colors.HexColor("#DC2626"), "major": colors.HexColor("#EA580C"),
              "minor": colors.HexColor("#CA8A04"), "info": colors.HexColor("#2563EB")}
    W = A4[0] - 30 * mm

    def footer(c, d):
        c.saveState()
        c.setFont(body_font, 7)
        c.drawString(15 * mm, 8 * mm, f"Comproof {meta.get('Comparison', meta.get('Audit ID', ''))} · " +
                     messages.FOOTER_L.get(lang, messages.FOOTER_L["en"]).format(
                         e=result["engine_version"], h=str(meta.get("Result SHA-256", ""))[:16]).rstrip("…") + "…")
        c.drawRightString(A4[0] - 15 * mm, 8 * mm, f"{L['page'] if lang != 'ar' else 'Page'} {d.page}")
        c.restoreState()

    def img_flow(p, max_w, max_h=70 * mm):
        if not p or not os.path.exists(p):
            return Paragraph(f"<i>{L['no_shot']}</i>", small) if lang != "ar" else Paragraph("—", small)
        im = Image.open(p).convert("RGB")
        r = min(max_w / im.width, max_h / im.height, 1.0 * mm * 0.22)
        im.thumbnail((1100, 1100))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        buf.seek(0)
        w0, h0 = Image.open(p).size
        return RLImage(buf, w0 * r, h0 * r)

    from xml.sax.saxutils import escape

    def txt_flow(t, w, lines=12, size=17):
        """Plain paragraph, or an image of the text when it contains Arabic (never black boxes)."""
        t = str(t or "")
        if has_arabic(t):
            im = text_image(t, 1100, size, lines)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            buf.seek(0)
            r = w / im.width
            return RLImage(buf, im.width * r, im.height * r)
        return Paragraph(escape(t[:900]) or "—", small)

    def cell(text):
        return txt_flow(text, 40 * mm, 2) if has_arabic(str(text)) else str(text)

    story = [txt_flow(L["report"], W, 1, 26) if lang == "ar" else Paragraph(L["report"], h1)]
    rows = [[cell(messages.meta_key(k, lang)), txt_flow(v, W - 47 * mm, 4)] for k, v in meta.items() if not k.startswith("_")]
    t = Table(rows, colWidths=[45 * mm, W - 45 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 6 * mm)]

    # summary
    hstyle = ParagraphStyle("hs", parent=small, textColor=colors.white, fontName=bold_font, fontSize=7, leading=9)
    summ = [[cell(x) if has_arabic(x) else Paragraph(escape(x), hstyle)
             for x in (L["level"], L["critical"], L["major"], L["minor"], L["info"],
                       L["confirmed"], L["not_deviation"], L["pending"])]]
    for s in _steps(result):
        fs = [f for f in result["findings"] if f["step"] == s]
        cnt = lambda sev: sum(f["severity"] == sev for f in fs)
        dec = lambda d: sum(decisions.get(f["id"], {}).get("decision", "pending") == d for f in fs)
        summ.append([cell(step_names[s]) if lang == "ar" else Paragraph(step_names[s], small),
                     cnt("critical"), cnt("major"), cnt("minor"), cnt("info"),
                     dec("confirmed"), dec("not_deviation") + dec("rejected"), dec("pending")])
    t = Table(summ, colWidths=[50 * mm] + [(W - 50 * mm) / 7] * 7)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    story += [txt_flow(L["summary"], W, 1, 20) if lang == "ar" else Paragraph(L["summary"], h2), t, Spacer(1, 4 * mm)]

    if signatures:
        srows = [[cell(L["meaning"]), cell(L["name"]), cell(L["datetime"]), cell(L["statement"])]]
        for s in signatures:
            srows.append([s["meaning"], s["user_name"], s["at"], Paragraph(s.get("statement", ""), small)])
        t = Table(srows, colWidths=[28 * mm, 40 * mm, 38 * mm, W - 106 * mm])
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
        story += [txt_flow(L["signatures"], W, 1, 20) if lang == "ar" else Paragraph(L["signatures"], h2), t]

    show_info = meta.get("_include_info", False)
    for s in _steps(result):
        fs = [f for f in result["findings"] if f["step"] == s and (show_info or f["severity"] != "info"
              or decisions.get(f["id"], {}).get("decision") == "confirmed")]
        story += [PageBreak(), txt_flow(step_names[s], W, 1, 20) if lang == "ar" else Paragraph(step_names[s], h2)]
        if not fs:
            story.append(txt_flow(L["no_findings"], W, 1) if lang == "ar" else Paragraph(L["no_findings"], ss["Normal"]))
        for f in fs:
            dec = decisions.get(f["id"], {})
            ai = f.get("ai") or {}
            hdr = Table([[f["id"], cell(sev_l.get(f["severity"], f["severity"]).upper() if lang != "ar" else sev_l[f["severity"]]),
                          txt_flow(f["title"], W - 66 * mm, 2),
                          cell(L["st"].get(dec.get("decision", "pending"), dec.get("decision", "pending")))]],
                        colWidths=[14 * mm, 20 * mm, W - 64 * mm, 30 * mm])
            hdr.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                                     ("BACKGROUND", (1, 0), (1, 0), sevcol.get(f["severity"], colors.grey)),
                                     ("TEXTCOLOR", (1, 0), (1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                     ("BOX", (0, 0), (-1, -1), 0.4, colors.grey)]))
            half = (W - 4 * mm) / 2
            if s == 1:
                body = [[img_flow(os.path.join(shots_dir, f"{f['id']}_approved.jpg"), W - 4 * mm)],
                        [txt_flow(f["ref_text"], W - 4 * mm)]]
                bt = Table(body, colWidths=[W])
                bt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
            body = [[txt_flow(L["approved"], half, 1) if lang == "ar" else Paragraph(f"<b>{L['approved']}</b>", small),
                     txt_flow(L["design"], half, 1) if lang == "ar" else Paragraph(f"<b>{L['design']}</b>", small)],
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
                                                    f.get("where_ref") and f"{L['approved']}: " + f["where_ref"],
                                                    f.get("where_des") and f"{L['design']}: " + f["where_des"]) if x))
            if f.get("explanation"):
                notes.append(f"{L['what']}: " + f["explanation"])
            if f.get("action"):
                notes.append(f"{L['action']}: " + f["action"])
            if ai.get("explanation"):
                notes.append(f"{L['ai']} ({ai.get('verdict', '')}): {ai['explanation']}")
            if f.get("note"):
                notes.append(f["note"])
            if dec.get("comment"):
                notes.append(f"{L['reviewer']} ({dec.get('user', '')}): {dec['comment']}")
            block = [hdr, bt] + [txt_flow(n, W, 6) for n in notes] + [Spacer(1, 4 * mm)]
            story.append(KeepTogether(block))
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=L["report"], author="Comproof · Comp11 Labs",
                            lang={"en": "en-GB", "fr": "fr-FR", "ar": "ar"}.get(lang, "en"))
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


def html_report(result: dict, decisions: dict, shots_dir: str, path: str, meta: dict, signatures: list,
                lang: str = "en"):
    """Self-contained interactive report (one HTML file with embedded images) to send to people
    who have no Comproof account. Decisions and signatures are shown, not editable."""
    import jinja2
    tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tpl_dir), autoescape=True)
    labels = dict(messages.HTML_LABELS.get(lang, messages.HTML_LABELS["en"]),
                  steps=messages.STEP_NAMES_L.get(lang, messages.STEP_NAMES_L["en"]),
                  stepsSub=messages.STEP_SUBS_L.get(lang, messages.STEP_SUBS_L["en"]))
    data = {
        "mode": "file", "lang": lang, "labels": labels,
        "findings": messages.localize_findings(result["findings"], lang), "exclusions": result["exclusions"],
        "decisions": {k: {"decision": v["decision"], "comment": v.get("comment"), "user": v.get("user"), "at": v.get("at")}
                      for k, v in decisions.items()},
        "sizes": {"approved": result["approved"]["sizes"], "design": result["design"]["sizes"]},
        "images": standalone_images(result, shots_dir), "imgBase": "", "canDecide": False, "decideUrl": "", "csrf": "",
    }
    html = env.get_template("report.html").render(mode="file", lang=lang, T=labels, meta=meta, sigs=signatures,
                                                  urls={}, can_sign=False, data=data)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
