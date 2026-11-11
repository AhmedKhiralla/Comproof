"""End-to-end: artwork library, comparison engine, decisions, electronic signatures, exports, isolation."""
from __future__ import annotations

import io
import time

import pytest

from conftest import sign_in_first_time

APPROVED = [
    "1. NAME OF THE MEDICINAL PRODUCT",
    "Nerkardou 2.5 mg Oral dissolvable film",
    "2. QUALITATIVE AND QUANTITATIVE COMPOSITION",
    "Each Nerkardou 2.5 mg film contains 2.5 mg of bisoprolol fumarate.",
    "For the full list of excipients, see section 6.1.",
    "4.2 Posology and method of administration",
    "Instructions on handling the Oro-dispersible film.",
    "The maximum recommended dose is 10 mg once daily.",
    "Store at a temperature not exceeding 30 C in a dry place.",
]
DESIGN = [
    "1. NAME OF THE MEDICINAL PRODUCT",
    "Nerkardou 2.5 mg Oral dissolvable film",
    "2. QUALITATIVE AND QUANTITATIVE COMPOSITION",
    "Each Nerkardou 2.5 mg film contains 5 mg of bisoprolol fumarate.",
    "For the full list of excipients, see section 6.1",
    "4.2 Posology and method of administration",
    "Instructions on handling the Oral dissolvable film.",
    "The maximum recommended dose is 10mg once daily.",
    "Store at a temperature not exceeding 30 C in a dry place.",
]


def _pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 780
    for ln in lines:
        c.setFont("Helvetica", 11)
        c.drawString(60, y, ln)
        y -= 22
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def acme(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "CMPR", "name": "Compare Pharma", "country": "EG", "timezone": "Africa/Cairo",
        "default_language": "en", "admin": {"email": "admin@cmpr.test", "full_name": "Cmpr Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@cmpr.test", body["temporary_password"], "Admin#Cmpr2026")
    status, site, _ = admin.post("/api/sites", {"code": "OCT", "name": "October plant"})
    assert status == 200, site
    people = {}
    for key, roles in (("editor", ["artwork_editor"]), ("reviewer", ["reviewer"]),
                       ("approver", ["approver"]), ("viewer", ["viewer"])):
        st, b, _ = admin.post("/api/users", {"email": f"{key}@cmpr.test", "full_name": key.title(),
                                             "roles": [{"site_id": site["id"], "role": r} for r in roles]})
        assert st == 200, b
        pw = f"{key.title()}#Pass2026"
        people[key] = (sign_in_first_time(server, f"{key}@cmpr.test", b["temporary_password"], pw), pw)
    return {"admin": admin, "site": site, **people}


def test_library_and_master_signature(acme):
    editor, _ = acme["editor"]
    viewer, _ = acme["viewer"]
    st, p, _ = viewer.post("/api/products", {"code": "NRK", "name": "Nerkardou"})
    assert st == 403
    st, p, _ = editor.post("/api/products", {"code": "nrk", "name": "Nerkardou", "markets": ["eg", "SA"],
                                             "strengths": "2.5, 5, 10 mg"})
    assert st == 200 and p["code"] == "NRK" and p["markets"] == ["EG", "SA"], p
    st, p, _ = editor.post(f"/api/products/{p['id']}/components",
                           {"code": "NRK-PIL", "kind": "leaflet", "name": "Patient leaflet", "languages": ["en"]})
    assert st == 200, p
    comp = p
    st, f, = editor.upload("/api/files", "approved.pdf", _pdf(APPROVED))
    assert st == 200 and f["doc_kind"] == "pdf-vector" and len(f["sha256"]) == 64, f
    st, bad = editor.upload("/api/files", "virus.exe", b"MZ\x90\x00binary")
    assert st == 422
    st, c, _ = editor.post(f"/api/components/{comp['id']}/artwork", {"version": "01", "file_id": f["id"],
                                                                     "change_control": "CC-2026-118"})
    assert st == 200 and c["versions"][0]["status"] == "draft", c
    ver = c["versions"][0]
    approver, apw = acme["approver"]
    # editors cannot sign; wrong password is refused and audited
    st, err, _ = editor.post(f"/api/artwork/{ver['id']}/sign", {"meaning": "approved_master", "email": "editor@cmpr.test",
                                                                 "password": "Editor#Pass2026"})
    assert st == 403
    st, err, _ = approver.post(f"/api/artwork/{ver['id']}/sign", {"meaning": "approved_master",
                                                                   "email": "approver@cmpr.test", "password": "wrong"})
    assert st == 403 and err["error"]["code"] == "bad_signature"
    st, c, _ = approver.post(f"/api/artwork/{ver['id']}/sign", {"meaning": "approved_master",
                                                                 "email": "approver@cmpr.test", "password": apw})
    assert st == 200 and c["versions"][0]["status"] == "effective", c
    assert c["versions"][0]["signatures"][0]["meaning"] == "approved_master"
    acme["component"] = comp
    st, audit, _ = acme["admin"].get("/api/audit?action=SIGNATURE_FAILED")
    assert st == 200 and audit["total"] >= 1


def _wait(client, cid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        st, s, _ = client.get(f"/api/comparisons/{cid}/status")
        assert st == 200, s
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(1)
    raise AssertionError("comparison did not finish")


def test_comparison_run_and_findings(acme):
    reviewer, _ = acme["reviewer"]
    viewer, _ = acme["viewer"]
    st, f = reviewer.upload("/api/files", "design.pdf", _pdf(DESIGN))
    assert st == 200
    body = {"site_id": acme["site"]["id"], "title": "Nerkardou PIL proof v1", "component_id": acme["component"]["id"],
            "test_file_id": f["id"], "languages": ["eng"], "supplier": "Delta Print"}
    st, err, _ = viewer.post("/api/comparisons", body)
    assert st == 403
    st, c, _ = reviewer.post("/api/comparisons", body)
    assert st == 200 and c["number"].startswith("CP-"), c
    s = _wait(reviewer, c["id"])
    assert s["status"] == "review", s
    st, d, _ = reviewer.get(f"/api/comparisons/{c['id']}")
    assert st == 200
    res = d["result"]
    by_kind = {}
    for x in res["findings"]:
        by_kind.setdefault(x["kind"], []).append(x)
    numeric = [x for x in by_kind.get("numeric", []) if "2.5" in x["ref_text"] and "5" in x["des_text"]]
    assert numeric and numeric[0]["severity"] == "critical", by_kind.keys()
    changed = [x for x in res["findings"] if x["step"] == 2 and "Oro-dispersible" in x["ref_text"]]
    assert changed and changed[0]["severity"] in ("major", "critical"), [x["ref_text"] for x in res["findings"]]
    spacing = [x for x in res["findings"] if x["step"] == 3 and x["kind"] == "spacing" and "10mg" in x["des_text"]]
    assert spacing, [(x["kind"], x["ref_text"], x["des_text"]) for x in res["findings"] if x["step"] == 3]
    punct = [x for x in res["findings"] if x["step"] == 3 and x["kind"] == "punctuation" and "6.1" in x["ref_text"]]
    assert punct, [(x["kind"], x["ref_text"], x["des_text"]) for x in res["findings"] if x["step"] == 3]
    assert res["ai"]["vision_model"] and res["ai"]["science_model"]
    assert any(x["kind"] == "ai_science" for x in res["findings"])
    # screenshots are served and integrity-checked
    shot = next(x for x in res["findings"] if x["ref_crop"])
    st, img, _ = reviewer.get(f"/api/comparisons/{c['id']}/images/{shot['id']}_approved.jpg", raw=True)
    assert st == 200 and img[:3] == b"\xff\xd8\xff"
    st, _, _ = reviewer.get(f"/api/comparisons/{c['id']}/images/..%2f..%2fetc.jpg", raw=True)
    assert st in (404, 503)  # never served
    st, _, _ = reviewer.get(f"/api/comparisons/{c['id']}/images/result.json", raw=True)
    assert st == 404
    acme["cmp"] = d


def test_review_and_signature_rules(acme):
    reviewer, rpw = acme["reviewer"]
    approver, apw = acme["approver"]
    d = acme["cmp"]
    cid = d["id"]
    real = [x for x in d["result"]["findings"] if x["severity"] != "info"]
    # a reason is required to dismiss a finding
    st, err, _ = reviewer.post(f"/api/comparisons/{cid}/decisions", {"finding_id": real[0]["id"], "decision": "not_deviation"})
    assert st == 422
    # approvers cannot record decisions (no reviewer role)
    st, err, _ = approver.post(f"/api/comparisons/{cid}/decisions", {"finding_id": real[0]["id"], "decision": "confirmed"})
    assert st == 403
    # sign review with open findings is refused
    st, err, _ = reviewer.post(f"/api/comparisons/{cid}/sign", {"meaning": "reviewed", "email": "reviewer@cmpr.test", "password": rpw})
    assert st == 409 and err["error"]["code"] == "open_findings"
    for x in real:
        dec = "confirmed" if x["severity"] in ("critical", "major") else "not_deviation"
        st, r, _ = reviewer.post(f"/api/comparisons/{cid}/decisions",
                                 {"finding_id": x["id"], "decision": dec, "comment": "Checked against the approved scan"})
        assert st == 200, r
    # approval before review is refused (four eyes)
    st, err, _ = approver.post(f"/api/comparisons/{cid}/sign", {"meaning": "approved", "email": "approver@cmpr.test", "password": apw})
    assert st == 409 and err["error"]["code"] == "four_eyes"
    st, d2, _ = reviewer.post(f"/api/comparisons/{cid}/sign", {"meaning": "reviewed", "email": "reviewer@cmpr.test", "password": rpw})
    assert st == 200 and d2["signatures"][-1]["meaning"] == "reviewed", d2
    # confirmed critical deviations block approval
    st, err, _ = approver.post(f"/api/comparisons/{cid}/sign", {"meaning": "approved", "email": "approver@cmpr.test", "password": apw})
    assert st == 409 and err["error"]["code"] == "confirmed_deviations"
    st, err, _ = approver.post(f"/api/comparisons/{cid}/sign", {"meaning": "rejected", "email": "approver@cmpr.test", "password": apw})
    assert st == 422  # reason required
    st, d3, _ = approver.post(f"/api/comparisons/{cid}/sign", {"meaning": "rejected", "email": "approver@cmpr.test",
                                                               "password": apw, "reason": "Strength in section 2 is wrong."})
    assert st == 200 and d3["status"] == "rejected", d3
    assert d3["signatures"][-1]["record_hash"] == d3["result_sha256"]
    # a closed comparison takes no more decisions
    st, err, _ = reviewer.post(f"/api/comparisons/{cid}/decisions", {"finding_id": real[0]["id"], "decision": "confirmed"})
    assert st == 409


def test_records_cannot_be_altered_in_database(db_url, acme):
    import psycopg
    conn = psycopg.connect(db_url)
    tid = str(acme["cmp"]["tenant_id"])
    for sql in ("UPDATE finding_decisions SET decision = 'confirmed'", "DELETE FROM signatures",
                "UPDATE files SET filename = 'x'", "DELETE FROM comparisons",
                "UPDATE comparisons SET status = 'approved'", "UPDATE comparisons SET result_sha256 = 'x'"):
        conn.execute("SET LOCAL ROLE comproof_app")
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tid,))
        with pytest.raises(psycopg.Error):
            conn.execute(sql)
        conn.rollback()
    # even the database owner cannot rewrite a signature or a decision
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE signatures SET meaning = 'approved'")
    conn.rollback()
    conn.close()


def test_exports(acme):
    viewer, _ = acme["viewer"]
    cid = acme["cmp"]["id"]
    for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK"), ("html", b"<!doctype")):
        st, data, hdr = viewer.get(f"/api/comparisons/{cid}/export.{fmt}", raw=True)
        assert st == 200 and data[:len(magic)].lower() == magic.lower(), (fmt, data[:40])
    st, audit, _ = acme["admin"].get(f"/api/audit?action=EXPORT&record_id={cid}")
    assert audit["total"] == 3


def test_other_company_cannot_see_comparison(acme, two_companies):
    other = two_companies["NILE"]["admin"]
    st, _, _ = other.get(f"/api/comparisons/{acme['cmp']['id']}")
    assert st == 404
    st, lst, _ = other.get("/api/comparisons")
    assert st == 200 and lst["items"] == []


def test_admin_who_is_also_approver_can_sign_master(server, acme):
    """A company administrator keeps the site roles they hold, so the app offers them the approval signature."""
    admin = acme["admin"]
    st, b, _ = admin.post("/api/users", {"email": "boss@cmpr.test", "full_name": "Boss", "is_tenant_admin": True,
                                         "roles": [{"site_id": acme["site"]["id"], "role": r}
                                                   for r in ("artwork_editor", "approver")]})
    assert st == 200, b
    boss = sign_in_first_time(server, "boss@cmpr.test", b["temporary_password"], "Boss#Pass2026")
    st, me, _ = boss.get("/api/auth/me")
    site = next(s for s in me["sites"] if s["id"] == acme["site"]["id"])
    assert "admin" in site["roles"] and "approver" in site["roles"], site
    st, p, _ = boss.post("/api/products", {"code": "BOSS", "name": "Boss product"})
    st, comp, _ = boss.post(f"/api/products/{p['id']}/components", {"code": "BOSS-PIL", "kind": "leaflet", "name": "PIL"})
    st, f = boss.upload("/api/files", "boss.pdf", _pdf(APPROVED[:3]))
    st, c, _ = boss.post(f"/api/components/{comp['id']}/artwork", {"version": "01", "file_id": f["id"]})
    ver = c["versions"][0]
    st, c, _ = boss.post(f"/api/artwork/{ver['id']}/sign", {"meaning": "approved_master", "email": "boss@cmpr.test",
                                                            "password": "Boss#Pass2026"})
    assert st == 200 and c["versions"][0]["status"] == "effective", c


def test_lost_file_is_restored_by_uploading_the_same_bytes(acme):
    """If the file store loses a file, re-uploading identical bytes restores it and the run can be retried."""
    import os
    from conftest import BACKEND
    reviewer, _ = acme["reviewer"]
    data = _pdf(DESIGN[:5] + ["Lost and restored."])
    st, f = reviewer.upload("/api/files", "restore.pdf", data)
    assert st == 200
    path = next((BACKEND / "tests" / ".data").rglob(f["sha256"] + ".pdf"))
    os.chmod(path, 0o640)
    os.remove(path)
    body = {"site_id": acme["site"]["id"], "title": "Lost file", "component_id": acme["component"]["id"],
            "test_file_id": f["id"], "languages": ["eng"]}
    st, c, _ = reviewer.post("/api/comparisons", body)
    assert st == 200, c
    s = _wait(reviewer, c["id"])
    assert s["status"] == "failed" and "Upload the same file again" in (s.get("progress") or ""), s
    st, g = reviewer.upload("/api/files", "restore again.pdf", data)
    assert st == 200 and g["sha256"] == f["sha256"]
    st, _, _ = reviewer.post(f"/api/comparisons/{c['id']}/retry")
    assert st == 200
    assert _wait(reviewer, c["id"])["status"] == "review"


def test_uploads_refused_on_railway_without_volume(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p1")
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    assert Settings().storage_persistent is False
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/vol")
    s = Settings()
    assert s.storage_persistent is True and s.data_dir == "/vol"


def test_review_of_draft_approved_material_without_test_file(acme):
    """Level 1 on the approved material alone: a draft version can be reviewed before an approver signs it."""
    editor, _ = acme["editor"]
    reviewer, _ = acme["reviewer"]
    faulty = [l.replace("contains 2.5 mg", "contains 5 mg") for l in APPROVED] + ["Tablets must be swallowed whole."]
    st, f = editor.upload("/api/files", "draft v02.pdf", _pdf(faulty))
    assert st == 200
    st, c, _ = editor.post(f"/api/components/{acme['component']['id']}/artwork", {"version": "02", "file_id": f["id"]})
    draft = next(v for v in c["versions"] if v["version"] == "02")
    assert draft["status"] == "draft"
    body = {"site_id": acme["site"]["id"], "title": "Review of draft v02", "purpose": "master_review",
            "component_id": acme["component"]["id"], "artwork_version_id": draft["id"], "languages": ["eng"]}
    st, err, _ = reviewer.post("/api/comparisons", dict(body, purpose="proof"))
    assert st == 422 and "test_file_id" in err["error"]["fields"]          # a comparison still needs a test file
    st, cm, _ = reviewer.post("/api/comparisons", body)
    assert st == 200, cm
    assert _wait(reviewer, cm["id"])["status"] == "review"
    st, d, _ = reviewer.get(f"/api/comparisons/{cm['id']}")
    res = d["result"]
    assert d["comparison"]["test_file_id"] is None if "comparison" in d else d["test_file_id"] is None
    assert res["review_only"] and res["design"]["pages"] == 0
    steps = {x["step"] for x in res["findings"]}
    assert steps <= {1, 5, 7} and 1 in steps, steps
    lvl1 = " | ".join(f"{x['title']} {x['explanation']}" for x in res["findings"] if x["step"] == 1)
    assert "2.5" in lvl1 and "5 mg" in lvl1, lvl1                            # strength contradiction found
    assert all(x["des_loc"] == [] for x in res["findings"])
    st, pdfb, _ = reviewer.get(f"/api/comparisons/{cm['id']}/export.pdf", raw=True)
    assert st == 200 and pdfb[:4] == b"%PDF"
    st, lst, _ = reviewer.get("/api/comparisons")
    assert any(x["id"] == cm["id"] and x["test_filename"] is None for x in lst["items"])


APPROVED_FR = [
    "1. DÉNOMINATION DU MÉDICAMENT",
    "Nerkardou 2,5 mg film orodispersible",
    "2. COMPOSITION QUALITATIVE ET QUANTITATIVE",
    "Chaque film de Nerkardou 2,5 mg contient 2,5 mg de fumarate de bisoprolol.",
    "Pour la liste complète des excipients, voir rubrique 6.1.",
    "4.2 Posologie et mode d'administration",
    "La dose maximale recommandée est de 10 mg une fois par jour.",
    "A conserver à une température ne dépassant pas 30 C.",
]
DESIGN_FR = [
    "1. DÉNOMINATION DU MÉDICAMENT",
    "Nerkardou 2,5 mg film orodispersible",
    "2. COMPOSITION QUALITATIVE ET QUANTITATIVE",
    "Chaque film de Nerkardou 2,5 mg contient 5 mg de fumarate de bisoprolol.",
    "Pour la liste complète des excipients, voir rubrique 6.1.",
    "4.2 Posologie et mode d'administration",
    "La dose maximale recommandée est de 20 mg une fois par jour.",
    "A conserver à une température ne dépassant pas 30 C.",
]


def test_french_comparison(acme):
    """A French leaflet is compared in French: fra is accepted end to end, decimal commas are understood,
    French section headings are recognised, and the changed numbers are found."""
    editor, _ = acme["editor"]
    st, p, _ = editor.post("/api/products", {"code": "NRKF", "name": "Nerkardou FR", "strengths": "2.5, 5, 10 mg"})
    assert st == 200, p
    st, comp, _ = editor.post(f"/api/products/{p['id']}/components",
                              {"code": "NRKF-PIL", "kind": "leaflet", "name": "Notice patient", "languages": ["fr"]})
    assert st == 200, comp
    st, f, = editor.upload("/api/files", "approuve.pdf", _pdf(APPROVED_FR))
    assert st == 200, f
    st, c, _ = editor.post(f"/api/components/{comp['id']}/artwork", {"version": "01", "file_id": f["id"]})
    assert st == 200, c
    approver, apw = acme["approver"]
    st, c, _ = approver.post(f"/api/artwork/{c['versions'][0]['id']}/sign",
                             {"meaning": "approved_master", "email": "approver@cmpr.test", "password": apw})
    assert st == 200, c
    reviewer, _ = acme["reviewer"]
    st, f, = reviewer.upload("/api/files", "epreuve.pdf", _pdf(DESIGN_FR))
    assert st == 200
    st, c, _ = reviewer.post("/api/comparisons", {"site_id": acme["site"]["id"], "title": "Notice FR épreuve 1",
                                                  "component_id": comp["id"], "test_file_id": f["id"],
                                                  "languages": ["fra"], "supplier": "Imprimerie Alger"})
    assert st == 200, c
    s = _wait(reviewer, c["id"])
    assert s["status"] == "review", s
    st, d, _ = reviewer.get(f"/api/comparisons/{c['id']}")
    res = d["result"]
    assert res["reading_order"].get("fra"), res["reading_order"]
    fra = [x for x in res["findings"] if x["lang"] == "fra"]
    assert fra, [x["lang"] for x in res["findings"]]
    # Level 1 findings on a French master are French findings, not English
    assert all(x["lang"] == "fra" for x in res["findings"] if x["step"] == 1), \
        [(x["id"], x["lang"]) for x in res["findings"] if x["step"] == 1]
    # 2,5 -> 5 in the composition: a changed number, critical
    numeric = [x for x in fra if x["kind"] == "numeric" and "5" in x["des_text"] and "2.5" in x["ref_text"].replace(",", ".")]
    assert numeric and numeric[0]["severity"] == "critical", [(x["kind"], x["ref_text"], x["des_text"]) for x in fra]
    # 10 mg -> 20 mg maximum dose
    dose = [x for x in fra if "10" in x["ref_text"] and "20" in x["des_text"]]
    assert dose, [(x["kind"], x["ref_text"], x["des_text"]) for x in fra]
    # French section headings are recognised and used as the finding's section
    secs = {x.get("section", "") for x in fra}
    assert any("Posologie" in s_ or "DÉNOMINATION" in s_ or "COMPOSITION" in s_ for s_ in secs), secs
    # findings carry a message key and parameters, so the UI can say them in the viewer's language
    assert numeric[0]["key"] == "txt.numeric" and numeric[0]["params"]["ref"], numeric[0]
    assert all("key" in x and "params" in x for x in res["findings"])

    # exports in the reader's language: French labels and finding texts, the document text unchanged
    import io as _io, zipfile
    st, pdfb, _ = reviewer.get(f"/api/comparisons/{c['id']}/export.pdf?lang=fr", raw=True)
    assert st == 200 and pdfb[:4] == b"%PDF"
    from pypdf import PdfReader
    txt = " ".join(" ".join(pg.extract_text() or "" for pg in PdfReader(_io.BytesIO(pdfb)).pages).split())
    for want in ("Rapport de comparaison", "Synthèse", "Nombre modifié", "Ce qui a changé", "Épreuve de maquette"):
        assert want in txt, (want, txt[:600])
    # the quoted document text is the material's own, unchanged
    assert " ".join(numeric[0]["des_text"].split()) in txt, numeric[0]["des_text"]
    assert "What changed" not in txt and "Number changed" not in txt
    st, xl, _ = reviewer.get(f"/api/comparisons/{c['id']}/export.xlsx?lang=fr", raw=True)
    assert st == 200
    import openpyxl
    wb = openpyxl.load_workbook(_io.BytesIO(xl))
    shared = " ".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v)
    shared += " " + " ".join(wb.sheetnames)
    for want in ("Gravité", "Ce qui a changé", "Nombre modifié", "Critique", "Constats"):
        assert want in shared, want
    st, html, _ = reviewer.get(f"/api/comparisons/{c['id']}/export.html?lang=fr", raw=True)
    import json as _json

    def embedded(h):
        h = h.decode()
        a = h.index('<script id="data" type="application/json">') + len('<script id="data" type="application/json">')
        return h, _json.loads(h[a:h.index("</script>", a)])
    html, data = embedded(html)
    assert st == 200 and 'lang="fr"' in html and "Rechercher un texte" in html
    assert data["labels"]["info"] == "Bruit OCR" and data["labels"]["steps"]["2"].startswith("Niveau 2")
    titles = [f["title"] for f in data["findings"]]
    assert any(t_.startswith("Nombre modifié") for t_ in titles), titles
    assert "Search text, section or ID" not in html
    st, html_en, _ = reviewer.get(f"/api/comparisons/{c['id']}/export.html?lang=en", raw=True)
    _, data_en = embedded(html_en)
    assert any(f["title"].startswith("Number changed") or f["kind"] != "numeric" for f in data_en["findings"])
    assert data_en["labels"]["info"] == "OCR noise"
