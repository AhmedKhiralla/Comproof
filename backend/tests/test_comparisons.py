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
