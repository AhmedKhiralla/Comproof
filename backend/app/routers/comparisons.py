"""Comparisons: start, follow, review (decisions), sign, export."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from typing import Literal

from pydantic import BaseModel, Field
from starlette.responses import FileResponse, Response

from .. import esign, storage
from ..api import ApiError, Call, endpoint, not_found
from ..defaults import effective_engine, effective_features
from ..perms import can_decide, can_start, require_signer, require_site, site_roles, visible_site_ids

SEV = ("critical", "major", "minor", "info")
_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
LIST_SQL = """
SELECT c.id, c.number, c.title, c.purpose, c.status, c.progress, c.site_id, s.code AS site_code,
       c.component_id, comp.code AS component_code, comp.kind AS component_kind, p.code AS product_code,
       p.name AS product_name, c.supplier, c.reference_no, c.result_summary, c.created_at, c.finished_at, c.closed_at,
       u.full_name AS created_by_name, rf.filename AS reference_filename, tf.filename AS test_filename
  FROM comparisons c
  JOIN sites s ON s.id = c.site_id
  JOIN files rf ON rf.id = c.reference_file_id
  JOIN files tf ON tf.id = c.test_file_id
  LEFT JOIN components comp ON comp.id = c.component_id
  LEFT JOIN products p ON p.id = comp.product_id
  LEFT JOIN users u ON u.id = c.created_by
"""


def _load(call: Call, cid: str) -> dict:
    c = call.tx.one(LIST_SQL.replace("SELECT c.id,", "SELECT c.*, c.id,") + " WHERE c.id = %s::uuid", cid)
    if not c:
        raise not_found("Comparison")
    require_site(call, str(c["site_id"]))
    return c


def load_result(c: dict) -> dict | None:
    if not c.get("result_sha256"):
        return None
    key = f"{c['id']}:{c['result_sha256']}"
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    path = os.path.join(storage.work_dir(c["tenant_id"], c["id"]), "result.json")
    if not os.path.exists(path):
        raise ApiError(409, "integrity", "The result file of this comparison is missing.")
    with open(path, "rb") as fh:
        raw = fh.read()
    if hashlib.sha256(raw).hexdigest() != c["result_sha256"]:
        raise ApiError(409, "integrity", "The result file no longer matches its recorded SHA-256; it was changed outside Comproof.")
    res = json.loads(raw)
    with _cache_lock:
        _cache[key] = res
        while len(_cache) > 12:
            _cache.popitem(last=False)
    return res


def _decisions(call: Call, cid: str) -> tuple[dict, list]:
    rows = call.tx.q("SELECT id, finding_id, decision, comment, user_id, user_name, decided_at FROM finding_decisions"
                     " WHERE comparison_id = %s::uuid ORDER BY id", cid)
    current = {}
    for r in rows:
        current[r["finding_id"]] = r
    return current, rows


def _open_items(res: dict, current: dict) -> list[str]:
    return [f["id"] for f in res["findings"] if f["severity"] != "info" and f["id"] not in current]


def _features(call: Call) -> dict:
    return effective_features(call.tx.val("SELECT features FROM tenants WHERE id = %s", call.tenant_id))


# ------------------------------------------------------------------ create
class ComparisonIn(BaseModel):
    site_id: str
    title: str = Field(min_length=1, max_length=200)
    purpose: Literal["proof", "printed_sample", "supplier_proof"] = "proof"
    component_id: str | None = None
    reference_file_id: str | None = None
    test_file_id: str
    supplier: str | None = Field(default=None, max_length=120)
    reference_no: str | None = Field(default=None, max_length=80)
    kind: Literal["leaflet", "carton", "label", "sachet", "blister_foil", "tube", "other"] | None = None
    languages: list[Literal["eng", "ara"]] = Field(default_factory=lambda: ["eng", "ara"], min_length=1)
    step1: bool = True
    step3: bool = True
    mirror_test: bool = False
    rotated_text: Literal["auto", "ignore", "read"] | None = None
    ai_read: bool | None = None
    # checks beyond the text (each also needs the company feature switched on)
    text: bool = True
    colour: bool = True
    barcodes: bool = True
    graphics: bool = True
    text_size: bool = True
    braille: bool = True
    dieline: bool = True
    shade_set_id: str | None = None            # default: the component's effective shade set
    sample_source: Literal["scan_target", "scan", "spectro", "photo"] = "scan"


@endpoint(auth="tenant_user", body=ComparisonIn)
def create_comparison(call: Call):
    b: ComparisonIn = call.body
    require_site(call, b.site_id)
    if not can_start(call, b.site_id):
        raise ApiError(403, "forbidden", "Reviewer or artwork editor access at this site is required to start a comparison.")
    tx = call.tx
    kind, artwork_id, ref_id, strengths = b.kind, None, b.reference_file_id, ""
    product_name, gtin, shade_id = "", None, b.shade_set_id
    if b.component_id:
        comp = tx.one("SELECT c.id, c.kind, c.languages, a.id AS artwork_id, a.file_id, p.strengths, p.name AS product_name,"
                      " p.gtin, (SELECT s.id FROM shade_sets s WHERE s.component_id = c.id AND s.status = 'effective')"
                      " AS shade_set_id FROM components c"
                      " JOIN products p ON p.id = c.product_id"
                      " LEFT JOIN artwork_versions a ON a.component_id = c.id AND a.status = 'effective'"
                      " WHERE c.id = %s::uuid AND c.active", b.component_id)
        if not comp:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"component_id": "Choose an active component."})
        kind = kind or comp["kind"]
        strengths = comp["strengths"] or ""
        product_name, gtin = comp["product_name"] or "", comp["gtin"]
        shade_id = shade_id or (str(comp["shade_set_id"]) if comp["shade_set_id"] else None)
        if not ref_id:
            if not comp["artwork_id"]:
                raise ApiError(422, "no_master", "This component has no effective approved artwork. Upload the approved file instead.",
                               fields={"reference_file_id": "No effective approved artwork."})
            ref_id, artwork_id = str(comp["file_id"]), comp["artwork_id"]
    if not ref_id:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"reference_file_id": "Upload the approved file."})
    for fid, field in ((ref_id, "reference_file_id"), (b.test_file_id, "test_file_id")):
        if not tx.val("SELECT 1 FROM files WHERE id = %s::uuid", fid):
            raise ApiError(422, "invalid", "Some fields need attention.", fields={field: "File was not found."})
    if ref_id == b.test_file_id:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"test_file_id": "The two files are the same file."})
    t = tx.one("SELECT features, engine FROM tenants WHERE id = %s", call.tenant_id)
    f, eng = effective_features(t["features"]), effective_engine(t["engine"])
    test_kind = tx.val("SELECT doc_kind FROM files WHERE id = %s::uuid", b.test_file_id)
    want_colour = b.colour and f["check_colour"]
    colour_cfg = None
    if want_colour and shade_id:
        sh = tx.one("SELECT id, status, verification, measurement_sha256, source FROM shade_sets WHERE id = %s::uuid"
                    " AND component_id = %s::uuid", shade_id, b.component_id)
        if not sh:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"shade_set_id": "Choose a shade set of this component."})
        if sh["status"] != "effective":
            raise ApiError(422, "invalid", "Some fields need attention.",
                           fields={"shade_set_id": "Only an approved (effective) shade set can be used as the reference."})
        sample_source = "spectro" if test_kind == "spectro" else b.sample_source
        if (sh["source"] == "spectro") != (sample_source == "spectro"):
            raise ApiError(422, "invalid", "Some fields need attention.",
                           fields={"test_file_id": "Measure the sample the same way as the shade set: spectrophotometer "
                                                   "files with spectrophotometer files, scans with scans."})
        colour_cfg = {"shade_set_id": str(sh["id"]), "measurement_sha256": sh["measurement_sha256"],
                      "tolerance": float(eng["colour_tolerance"]), "flat_tolerance": float(eng["flat_tolerance"]),
                      "sample_source": sample_source}
    elif test_kind == "spectro":
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"test_file_id": "A measurement file can only be checked against an approved shade set "
                                               "measured with a spectrophotometer."})
    do_text = b.text and test_kind != "spectro"
    k = kind or "leaflet"
    settings = {
        "kind": kind or "leaflet", "languages": b.languages,
        "strengths": sorted({x.replace(",", ".") for x in re.findall(r"\d+(?:[.,]\d+)?", strengths)}), "step1": b.step1 and f["step1_master_audit"],
        "step3": b.step3 and f["step3_typography"], "exclude_phrases": eng["exclude_phrases"],
        "rotated_text": b.rotated_text or eng["rotated_text"], "mirror_test": b.mirror_test,
        "ai": {"provider": eng["provider"], "reading_provider": eng["reading_provider"], "review": f["ai_review"],
               "science": f["ai_science"], "read": f["ai_reading"] if b.ai_read is None else (b.ai_read and f["ai_reading"])},
        "text": do_text,
        "checks": {"colour": colour_cfg, "barcodes": do_text and b.barcodes and f["check_barcodes"],
                   "graphics": do_text and b.graphics and f["check_graphics"],
                   "text_size": do_text and b.text_size and f["check_text_size"],
                   "braille": do_text and b.braille and f["check_braille"],
                   "dieline": do_text and b.dieline and f["check_dieline"]},
        "product": {"name": product_name, "gtin": gtin, "purpose": b.purpose},
        "min_font_pt": float((eng.get("min_font_pt") or {}).get(k, 7.0)),
        "braille_required": k in (eng.get("braille_required") or []),
        "cut_margin_mm": float(eng.get("cut_margin_mm", 1.5)),
    }
    number = tx.val("SELECT cp_next_comparison_number(%s::uuid)", call.tenant_id)
    row = tx.one(
        "INSERT INTO comparisons (tenant_id, site_id, number, title, purpose, component_id, artwork_version_id,"
        " reference_file_id, test_file_id, supplier, reference_no, settings, progress, shade_set_id)"
        " VALUES (%s, %s::uuid, %s, %s, %s, %s::uuid, %s, %s::uuid, %s::uuid, %s, %s, %s::jsonb, 'Waiting to start',"
        " %s::uuid) RETURNING id",
        call.tenant_id, b.site_id, number, b.title.strip(), b.purpose, b.component_id, artwork_id, ref_id,
        b.test_file_id, (b.supplier or "").strip() or None, (b.reference_no or "").strip() or None, json.dumps(settings),
        colour_cfg["shade_set_id"] if colour_cfg else None)
    from ..worker import wake
    wake()
    return {"id": row["id"], "number": number}


# ------------------------------------------------------------------ read
@endpoint(auth="tenant_user")
def list_comparisons(call: Call):
    q = call.query
    where, params = [], []
    sites = visible_site_ids(call)
    if sites is not None:
        if not sites:
            return {"items": [], "total": 0}
        where.append("c.site_id = ANY(%s::uuid[])")
        params.append(sites)
    if q.get("site_id"):
        where.append("c.site_id = %s::uuid"); params.append(q["site_id"])
    if q.get("status"):
        where.append("c.status = %s"); params.append(q["status"])
    if q.get("component_id"):
        where.append("c.component_id = %s::uuid"); params.append(q["component_id"])
    if q.get("q"):
        term = f"%{q['q'][:80]}%"
        where.append("(c.number ILIKE %s OR c.title ILIKE %s OR p.code ILIKE %s OR p.name ILIKE %s OR comp.code ILIKE %s"
                     " OR c.supplier ILIKE %s OR c.reference_no ILIKE %s)")
        params += [term] * 7
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    page = max(1, int(q.get("page") or 1))
    total = call.tx.val("SELECT count(*) FROM comparisons c LEFT JOIN components comp ON comp.id = c.component_id"
                        " LEFT JOIN products p ON p.id = comp.product_id" + sql_where, *params)
    items = call.tx.q(LIST_SQL + sql_where + " ORDER BY c.created_at DESC LIMIT 50 OFFSET %s", *params, (page - 1) * 50)
    return {"items": items, "total": total, "page": page}


@endpoint(auth="tenant_user")
def get_comparison(call: Call):
    cid = call.path["comparison_id"]
    c = _load(call, cid)
    res = load_result(c) if c["status"] in ("review", "approved", "rejected") else None
    current, history = _decisions(call, cid)
    sigs = esign.list_for(call, "comparison", cid)
    roles = site_roles(call, str(c["site_id"]))
    f = _features(call)
    me = str(call.user["id"])
    reviewed_by = {str(s["user_id"]) for s in sigs if s["meaning"] == "reviewed"}
    open_items = _open_items(res, current) if res else []
    blockers = []
    if res:
        if f["all_decided"] and open_items:
            blockers.append(f"{len(open_items)} findings have no decision yet.")
        if f["four_eyes"] and not (reviewed_by - {me}):
            blockers.append("A different person must sign the review first.")
        if f["four_eyes"] and me in reviewed_by:
            blockers.append("You signed the review, so another person must approve.")
        serious = [x["id"] for x in res["findings"] if x["severity"] in ("critical", "major")
                   and current.get(x["id"], {}).get("decision") == "confirmed"]
        if serious:
            blockers.append(f"{len(serious)} critical or major deviations are confirmed; reject instead.")
    out = {k: v for k, v in c.items() if k not in ("settings",)}
    out["settings"] = c["settings"]
    out["files"] = {
        "reference": call.tx.one("SELECT id, filename, sha256, page_count, doc_kind, size_bytes FROM files WHERE id = %s", c["reference_file_id"]),
        "test": call.tx.one("SELECT id, filename, sha256, page_count, doc_kind, size_bytes FROM files WHERE id = %s", c["test_file_id"]),
    }
    if c["artwork_version_id"]:
        out["artwork"] = call.tx.one("SELECT id, version, status, effective_from FROM artwork_versions WHERE id = %s",
                                     c["artwork_version_id"])
    out["result"] = res
    out["decisions"] = {k: {kk: v[kk] for kk in ("decision", "comment", "user_name", "decided_at")} for k, v in current.items()}
    out["decision_history"] = history
    out["signatures"] = sigs
    out["permissions"] = {
        "decide": c["status"] == "review" and can_decide(call, str(c["site_id"])),
        "sign_reviewed": c["status"] == "review" and "reviewer" in roles and me not in reviewed_by,
        "sign_approved": c["status"] == "review" and "approver" in roles,
        "sign_rejected": c["status"] == "review" and "approver" in roles,
        "cancel": c["status"] == "queued" and (call.user["is_tenant_admin"] or str(c["created_by"]) == me),
        "retry": c["status"] == "failed" and can_start(call, str(c["site_id"])),
    }
    out["approval_blockers"] = blockers
    out["features"] = {k: f[k] for k in ("four_eyes", "all_decided")}
    return out


@endpoint(auth="tenant_user")
def comparison_status(call: Call):
    c = _load(call, call.path["comparison_id"])
    return {"status": c["status"], "progress": c["progress"]}


@endpoint(auth="tenant_user")
def comparison_image(call: Call):
    c = _load(call, call.path["comparison_id"])
    name = call.path["name"]
    if not re.fullmatch(r"[A-Za-z0-9_]{1,40}\.jpg", name):
        raise not_found("Image")
    res = load_result(c)
    want = (res or {}).get("screenshots", {}).get(name)
    path = os.path.join(storage.work_dir(c["tenant_id"], c["id"]), "shots", name)
    if not want or not os.path.exists(path):
        raise not_found("Image")
    with open(path, "rb") as fh:
        data = fh.read()
    if hashlib.sha256(data).hexdigest() != want:
        raise ApiError(409, "integrity", "This screenshot no longer matches the result record.")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ review
class DecisionIn(BaseModel):
    finding_id: str = Field(pattern=r"^[A-Z][0-9]{1,6}$")
    decision: Literal["confirmed", "not_deviation"]
    comment: str | None = Field(default=None, max_length=1000)


@endpoint(auth="tenant_user", body=DecisionIn)
def decide(call: Call):
    cid = call.path["comparison_id"]
    c = _load(call, cid)
    b: DecisionIn = call.body
    if c["status"] != "review":
        raise ApiError(409, "closed", "Decisions can only be recorded while the comparison is in review.")
    if not can_decide(call, str(c["site_id"])):
        raise ApiError(403, "forbidden", "Reviewer access at this site is required to record decisions.")
    res = load_result(c)
    if b.finding_id not in {f["id"] for f in res["findings"]}:
        raise not_found("Finding")
    comment = (b.comment or "").strip()
    if b.decision == "not_deviation" and len(comment) < 3:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"comment": "Give the reason it is not a deviation."})
    row = call.tx.one(
        "INSERT INTO finding_decisions (tenant_id, comparison_id, finding_id, decision, comment, user_id, user_name)"
        " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s) RETURNING finding_id, decision, comment, user_name, decided_at",
        call.tenant_id, cid, b.finding_id, b.decision, comment or None, call.user["id"], call.user["full_name"])
    return row


class SignIn(BaseModel):
    meaning: Literal["reviewed", "approved", "rejected"]
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=1000)


@endpoint(auth="tenant_user", body=SignIn)
def sign_comparison(call: Call):
    cid = call.path["comparison_id"]
    c = _load(call, cid)
    b: SignIn = call.body
    if c["status"] != "review":
        raise ApiError(409, "closed", "Only a comparison in review can be signed.")
    require_signer(call, "reviewer" if b.meaning == "reviewed" else "approver", str(c["site_id"]))
    res = load_result(c)
    current, _ = _decisions(call, cid)
    sigs = esign.list_for(call, "comparison", cid)
    f = _features(call)
    me = str(call.user["id"])
    reviewed_by = {str(s["user_id"]) for s in sigs if s["meaning"] == "reviewed"}
    open_items = _open_items(res, current)
    if b.meaning == "reviewed":
        if me in reviewed_by:
            raise ApiError(409, "already_signed", "You have already signed the review of this comparison.")
        if f["all_decided"] and open_items:
            raise ApiError(409, "open_findings", f"{len(open_items)} findings still need a decision.", extra={"open": open_items})
    elif b.meaning == "approved":
        if f["all_decided"] and open_items:
            raise ApiError(409, "open_findings", f"{len(open_items)} findings still need a decision.", extra={"open": open_items})
        if f["four_eyes"]:
            if me in reviewed_by:
                raise ApiError(409, "four_eyes", "You signed the review; a different person must approve.")
            if not reviewed_by:
                raise ApiError(409, "four_eyes", "The review must be signed by a reviewer before approval.")
        serious = [x["id"] for x in res["findings"] if x["severity"] in ("critical", "major")
                   and current.get(x["id"], {}).get("decision") == "confirmed"]
        if serious:
            raise ApiError(409, "confirmed_deviations",
                           "Critical or major deviations are confirmed, so the comparison cannot be approved. Reject it instead.",
                           extra={"findings": serious})
    elif b.meaning == "rejected" and len((b.reason or "").strip()) < 3:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"reason": "Give the reason for rejection."})
    esign.sign(call, entity="comparison", record_id=cid, label=c["number"], meaning=b.meaning,
               record_hash=c["result_sha256"], email=b.email, password=b.password, reason=b.reason)
    if b.meaning in ("approved", "rejected"):
        call.tx.x("UPDATE comparisons SET status = %s WHERE id = %s::uuid", b.meaning, cid)
    return get_comparison.__wrapped__(call)


# ------------------------------------------------------------------ queue control
@endpoint(auth="tenant_user")
def cancel_comparison(call: Call):
    cid = call.path["comparison_id"]
    c = _load(call, cid)
    if c["status"] != "queued":
        raise ApiError(409, "not_queued", "Only a comparison that has not started can be cancelled.")
    if not (call.user["is_tenant_admin"] or str(c["created_by"]) == str(call.user["id"])):
        raise ApiError(403, "forbidden", "Only the person who started it or an administrator can cancel it.")
    call.tx.x("UPDATE comparisons SET status = 'cancelled', progress = 'Cancelled' WHERE id = %s::uuid", cid)
    return {"ok": True}


@endpoint(auth="tenant_user")
def retry_comparison(call: Call):
    cid = call.path["comparison_id"]
    c = _load(call, cid)
    if c["status"] != "failed":
        raise ApiError(409, "not_failed", "Only a failed comparison can be started again.")
    if not can_start(call, str(c["site_id"])):
        raise ApiError(403, "forbidden", "Reviewer or artwork editor access at this site is required.")
    call.tx.x("UPDATE comparisons SET status = 'queued', progress = 'Waiting to start', error = NULL WHERE id = %s::uuid", cid)
    from ..worker import wake
    wake()
    return {"ok": True}


# ------------------------------------------------------------------ exports
def _meta(call: Call, c: dict, res: dict) -> dict:
    tenant = call.tx.one("SELECT name, timezone FROM tenants WHERE id = %s", c["tenant_id"])
    files = {
        "ref": call.tx.one("SELECT filename, sha256 FROM files WHERE id = %s", c["reference_file_id"]),
        "test": call.tx.one("SELECT filename, sha256 FROM files WHERE id = %s", c["test_file_id"]),
    }
    ai_info = res.get("ai") or {}
    return {
        "Audit ID": c["number"], "Company": tenant["name"], "Product": c["title"],
        "Component": " ".join(x for x in (c.get("product_code"), c.get("component_code")) if x) or "—",
        "Site": c["site_code"], "Reference": c["reference_no"] or "—", "Supplier": c["supplier"] or "—",
        "Purpose": {"proof": "Artwork proof", "printed_sample": "Printed sample", "supplier_proof": "Print-house proof"}[c["purpose"]],
        "Started by": c["created_by_name"], "Started": _ts(c["created_at"]), "Completed": _ts(c["finished_at"]),
        "Status": c["status"],
        "Approved file": f"{files['ref']['filename']}  (SHA-256 {files['ref']['sha256'][:16]}…)",
        "Test file": f"{files['test']['filename']}  (SHA-256 {files['test']['sha256'][:16]}…)",
        "Engine": res.get("engine_version"), "Result SHA-256": c["result_sha256"],
        "AI models": "; ".join(f"{k}: {v}" for k, v in (("reading", ai_info.get("reading_model")),
                                                        ("review", ai_info.get("vision_model")),
                                                        ("science", ai_info.get("science_model"))) if v) or "not used",
        "Levels run": ", ".join(n for n, on in (("1 approved-text audit", (c.get("settings") or {}).get("step1", True)),
                                                ("2 content", True),
                                                ("3 punctuation and typography", (c.get("settings") or {}).get("step3", True)))
                                if on),
        "AI notes": " ".join(ai_info.get("notes") or []) or "—",
        "Reading order": ", ".join(f"{k}: approved {v['approved']}, test {v['design']}, similarity {v['similarity']}"
                                   for k, v in res.get("reading_order", {}).items()),
        "Printed": _ts(call.tx.val("SELECT now()")),
        "approved_name": files["ref"]["filename"], "approved_pages": res["approved"]["pages"],
        "design_name": files["test"]["filename"],
    }


def _ts(v) -> str:
    if not v:
        return "—"
    return v.strftime("%Y-%m-%d %H:%M UTC") if hasattr(v, "strftime") else str(v)


@endpoint(auth="tenant_user")
def export_comparison(call: Call):
    from ..engine import exports
    cid = call.path["comparison_id"]
    fmt = call.path["fmt"]
    if fmt not in ("pdf", "xlsx", "html"):
        raise not_found("Export")
    c = _load(call, cid)
    res = load_result(c)
    if not res:
        raise ApiError(409, "no_result", "This comparison has no result yet.")
    current, _ = _decisions(call, cid)
    dec = {k: {"decision": "confirmed" if v["decision"] == "confirmed" else "rejected", "comment": v["comment"],
               "user": v["user_name"], "at": _ts(v["decided_at"])} for k, v in current.items()}
    sigs = [{"meaning": s["meaning"].replace("_", " ").capitalize(), "statement": s["statement"], "at": _ts(s["signed_at"]),
             "user_name": s["user_name"], "reason": s["reason"]} for s in esign.list_for(call, "comparison", cid)]
    meta = _meta(call, c, res)
    wd = storage.work_dir(c["tenant_id"], c["id"])
    shots = os.path.join(wd, "shots")
    out_dir = os.path.join(wd, "exports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{c['number']}.{fmt}")
    if fmt == "pdf":
        exports.pdf(res, dec, shots, path, {k: v for k, v in meta.items() if not k.endswith(("_name", "_pages"))}, sigs)
        mime = "application/pdf"
    elif fmt == "xlsx":
        exports.excel(res, dec, shots, path, {k: v for k, v in meta.items() if not k.endswith(("_name", "_pages"))})
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        exports.html_report(res, dec, shots, path, meta, sigs)
        mime = "text/html"
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    call.tx.event("EXPORT", "comparisons", cid, c["number"], {"format": fmt, "sha256": sha})
    safe = re.sub(r"[^\w.\-]", "_", f"{c['number']}_{c['title']}")[:120]
    return FileResponse(path, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{safe}.{fmt}"'})
