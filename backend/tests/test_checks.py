"""End-to-end: shade standards (Standard / Light / Dark), colour check, barcode check, spectrophotometer files."""
from __future__ import annotations

import time

import pytest

from barcode_fixtures import pdf as barcode_pdf
from colour_fixtures import artwork, scan
from conftest import sign_in_first_time


@pytest.fixture(scope="module")
def co(server, platform):
    st, body, _ = platform.post("/api/platform/tenants", {
        "code": "TINT", "name": "Tint Pharma", "country": "EG", "timezone": "Africa/Cairo",
        "default_language": "en", "admin": {"email": "admin@tint.test", "full_name": "Tint Admin"}})
    assert st == 200, body
    admin = sign_in_first_time(server, "admin@tint.test", body["temporary_password"], "Admin#Tint2026")
    st, site, _ = admin.post("/api/sites", {"code": "OCT", "name": "October plant"})
    out = {"admin": admin, "site": site}
    for key, roles in (("qa", ["artwork_editor", "reviewer"]), ("approver", ["approver"])):
        st, b, _ = admin.post("/api/users", {"email": f"{key}@tint.test", "full_name": key.title(),
                                             "roles": [{"site_id": site["id"], "role": r} for r in roles]})
        pw = f"{key.title()}#Pass2026"
        out[key] = (sign_in_first_time(server, f"{key}@tint.test", b["temporary_password"], pw), pw)
    qa, _ = out["qa"]
    st, p, _ = qa.post("/api/products", {"code": "NRK", "name": "Nerkardou", "strengths": "2.5, 5, 10 mg",
                                         "gtin": "6221000012341"})
    assert st == 200 and p["gtin"] == "6221000012341", p
    st, comp, _ = qa.post(f"/api/products/{p['id']}/components", {"code": "NRK-CTN", "kind": "carton", "name": "Carton"})
    assert st == 200, comp
    out["comp"] = comp
    return out


def _upload(c, name, data):
    st, f = c.upload("/api/files", name, data)
    assert st == 200, f
    return f


def _wait(c, cid, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        st, s, _ = c.get(f"/api/comparisons/{cid}/status")
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(1)
    raise AssertionError("comparison did not finish")


def test_shade_set_verification_and_signature(co):
    qa, _ = co["qa"]
    ap, apw = co["approver"]
    comp = co["comp"]
    std = _upload(qa, "standard.png", scan(artwork(1.0), angle=0.0, scale=1.0))
    light = _upload(qa, "light.png", scan(artwork(0.82), angle=0.7, scale=0.97))
    dark = _upload(qa, "dark.png", scan(artwork(1.18), angle=-0.5, scale=1.02))
    # cards uploaded in the wrong slots: Light and Dark swapped -> verification fails, cannot be approved
    st, c, _ = qa.post(f"/api/components/{comp['id']}/shades", {"version": "S0", "source": "scan",
                       "standard_file_id": std["id"], "light_file_id": dark["id"], "dark_file_id": light["id"]})
    assert st == 200, c
    bad = c["shade_sets"][0]
    assert bad["verification"] == "fail" and "swapped" in " ".join(bad["measurement"]["messages"]), bad["measurement"]
    st, err, _ = ap.post(f"/api/shades/{bad['id']}/sign", {"meaning": "approved_master", "email": "approver@tint.test",
                                                           "password": apw})
    assert st == 409 and err["error"]["code"] == "verification_failed", err
    # correct slots
    st, c, _ = qa.post(f"/api/components/{comp['id']}/shades", {"version": "S1", "source": "scan",
                       "standard_file_id": std["id"], "light_file_id": light["id"], "dark_file_id": dark["id"],
                       "supplier": "Delta Print"})
    assert st == 200, c
    good = next(s for s in c["shade_sets"] if s["version"] == "S1")
    m = good["measurement"]
    assert good["verification"] == "pass" and len(m["inks"]) >= 4, m
    assert all("points" not in i for i in m["inks"])          # sample points stay on the server
    assert all(i["light"]["L"] > i["standard"]["L"] > i["dark"]["L"] for i in m["inks"] if i["status"] == "ok")
    st, img, _ = qa.get(f"/api/shades/{good['id']}/preview/standard.jpg", raw=True)
    assert st == 200 and img[:3] == b"\xff\xd8\xff"
    st, c, _ = ap.post(f"/api/shades/{good['id']}/sign", {"meaning": "approved_master", "email": "approver@tint.test",
                                                          "password": apw})
    assert st == 200, c
    assert next(s for s in c["shade_sets"] if s["version"] == "S1")["status"] == "effective"
    co["shade"] = good


def test_shade_measurement_cannot_change(db_url, co):
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as conn:
        with pytest.raises(Exception):
            conn.execute("UPDATE shade_sets SET verification = 'pass', measurement = '{}'::jsonb WHERE id = %s",
                         (co["shade"]["id"],))
        with pytest.raises(Exception):
            conn.execute("DELETE FROM shade_sets WHERE id = %s", (co["shade"]["id"],))


def test_colour_check_of_samples(co):
    qa, _ = co["qa"]
    ap, apw = co["approver"]
    comp = co["comp"]
    # the component needs an effective artwork master for a comparison
    master = _upload(qa, "master.pdf", barcode_pdf([("EAN13", "622100001234")]))
    st, c, _ = qa.post(f"/api/components/{comp['id']}/artwork", {"version": "01", "file_id": master["id"]})
    st, c, _ = ap.post(f"/api/artwork/{c['versions'][0]['id']}/sign", {"meaning": "approved_master",
                                                                       "email": "approver@tint.test", "password": apw})
    assert st == 200, c
    results = {}
    for name, strength in (("mid", 0.92), ("heavy", 1.4)):
        f = _upload(qa, f"sample-{name}.png", scan(artwork(strength), angle=-0.4, scale=0.99, cast=(0.97, 1.0, 1.03)))
        st, cm, _ = qa.post("/api/comparisons", {"site_id": co["site"]["id"], "title": f"Shade {name}",
                                                 "component_id": comp["id"], "test_file_id": f["id"], "text": False,
                                                 "purpose": "printed_sample"})
        assert st == 200, cm
        s = _wait(qa, cm["id"])
        assert s["status"] == "review", s
        st, d, _ = qa.get(f"/api/comparisons/{cm['id']}")
        res = d["result"]
        assert res["checks"]["colour"]["verdict"] in ("pass", "fail"), res["checks"]
        results[name] = res
    mid, heavy = results["mid"], results["heavy"]
    assert mid["checks"]["colour"]["verdict"] == "pass", [(i["name"], i.get("where")) for i in mid["checks"]["colour"]["inks"]]
    assert heavy["checks"]["colour"]["verdict"] == "fail"
    fails = [f for f in heavy["findings"] if f["step"] == 4 and f["severity"] in ("major", "critical")]
    assert fails and "darker than the Dark limit" in fails[0]["explanation"] and "density" in fails[0]["action"], fails[:1]
    assert not [f for f in mid["findings"] if f["step"] in (1, 2, 3)]       # text levels were switched off


def test_barcode_check(co):
    qa, _ = co["qa"]
    f = _upload(qa, "proof.pdf", barcode_pdf([("EAN13", "622100001235")]))
    st, cm, _ = qa.post("/api/comparisons", {"site_id": co["site"]["id"], "title": "Carton proof",
                                             "component_id": co["comp"]["id"], "test_file_id": f["id"],
                                             "languages": ["eng"], "colour": False})
    assert st == 200, cm
    assert _wait(qa, cm["id"])["status"] == "review"
    st, d, _ = qa.get(f"/api/comparisons/{cm['id']}")
    res = d["result"]
    rows = res["checks"]["barcodes"]["rows"]
    assert rows and rows[0]["status"] == "changed", rows
    crit = [x for x in res["findings"] if x["step"] == 5 and x["severity"] == "critical"]
    titles = " | ".join(x["title"] for x in crit)
    assert "content changed" in titles and "GTIN does not match the product record" in titles, titles
    st, img, _ = qa.get(f"/api/comparisons/{cm['id']}/images/{crit[0]['id']}_design.jpg", raw=True)
    assert st == 200
    st, pdfb, _ = qa.get(f"/api/comparisons/{cm['id']}/export.pdf", raw=True)
    assert st == 200 and pdfb[:4] == b"%PDF"


CGATS = """CGATS.17
BEGIN_DATA_FORMAT
SAMPLE_ID SAMPLE_NAME LAB_L LAB_A LAB_B
END_DATA_FORMAT
BEGIN_DATA
{rows}
END_DATA
"""


def _cgats(vals: dict) -> bytes:
    rows = "\n".join(f'{i} "{n}" {l} {a} {b}' for i, (n, (l, a, b)) in enumerate(vals.items(), 1))
    return CGATS.format(rows=rows).encode()


def test_spectrophotometer_shades_and_sample(co, server, platform):
    qa, _ = co["qa"]
    ap, apw = co["approver"]
    st, comp, _ = qa.post(f"/api/products/{co['comp']['product_id']}/components",
                          {"code": "NRK-LBL", "kind": "label", "name": "Label"})
    std = {"PMS 485": (48.0, 68.0, 52.0), "Process blue": (40.0, -5.0, -45.0)}
    light = {"PMS 485": (52.0, 63.0, 47.0), "Process blue": (45.0, -6.0, -40.0)}
    dark = {"PMS 485": (44.0, 70.0, 55.0), "Process blue": (36.0, -4.0, -48.0)}
    ids = [_upload(qa, f"{n}.cgats", _cgats(v))["id"] for n, v in (("std", std), ("light", light), ("dark", dark))]
    st, c, _ = qa.post(f"/api/components/{comp['id']}/shades", {"version": "SP1", "source": "spectro",
                       "standard_file_id": ids[0], "light_file_id": ids[1], "dark_file_id": ids[2]})
    assert st == 200, c
    sh = c["shade_sets"][0]
    assert sh["verification"] == "pass" and sh["measurement"]["confidence"] == "measured", sh["measurement"]
    st, c, _ = ap.post(f"/api/shades/{sh['id']}/sign", {"meaning": "approved_master", "email": "approver@tint.test",
                                                        "password": apw})
    assert st == 200
    master = _upload(qa, "label.pdf", barcode_pdf([("QR", "https://comp11labs.com/p/NRK-LBL")]))
    st, c, _ = qa.post(f"/api/components/{comp['id']}/artwork", {"version": "01", "file_id": master["id"]})
    ap.post(f"/api/artwork/{c['versions'][0]['id']}/sign", {"meaning": "approved_master", "email": "approver@tint.test",
                                                            "password": apw})
    sample = _upload(qa, "sample.cgats", _cgats({"PMS 485": (50.0, 65.5, 49.5), "Process blue": (30.0, 10.0, -30.0)}))
    st, cm, _ = qa.post("/api/comparisons", {"site_id": co["site"]["id"], "title": "Label ink check",
                                             "component_id": comp["id"], "test_file_id": sample["id"]})
    assert st == 200, cm
    assert _wait(qa, cm["id"])["status"] == "review"
    st, d, _ = qa.get(f"/api/comparisons/{cm['id']}")
    inks = {i["name"]: i for i in d["result"]["checks"]["colour"]["inks"]}
    assert inks["PMS 485"]["verdict"] == "pass", inks["PMS 485"]
    assert inks["Process blue"]["verdict"] == "fail", inks["Process blue"]
