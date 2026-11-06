"""Artwork library: products, packaging components, approved artwork versions and the file store."""
from __future__ import annotations

import re
from typing import Literal

import anyio.from_thread
from pydantic import BaseModel, Field, field_validator
from starlette.responses import FileResponse

from .. import esign, storage
from ..api import ApiError, Call, endpoint, not_found
from ..config import settings
from ..perms import can_edit_library, require_library_edit, require_signer

KINDS = ("leaflet", "carton", "label", "sachet", "blister_foil", "tube", "other")


def _markets(v: list[str]) -> list[str]:
    out = sorted({x.strip().upper() for x in v if x.strip()})
    if any(not re.match(r"^[A-Z]{2}$", x) for x in out):
        raise ValueError("Use two-letter country codes.")
    return out


def _code(v: str) -> str:
    v = v.strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9._/-]{0,39}$", v):
        raise ValueError("Use up to 40 letters, digits, dot, dash, slash or underscore.")
    return v


# ------------------------------------------------------------------ files
@endpoint(auth="tenant_user")
def upload_file(call: Call):
    """Raw body upload. ?filename=... The same bytes uploaded twice share one stored copy."""
    if not settings.storage_persistent:
        raise ApiError(503, "no_storage", "Uploads are switched off because this server has no persistent volume: "
                       "files would be lost at the next deploy. Attach a volume to the Comproof service in Railway.")
    filename = (call.query.get("filename") or "").strip()[:200]
    if not filename:
        raise ApiError(422, "invalid", "The file name is missing.")
    data = anyio.from_thread.run(call.request.body)
    if not data:
        raise ApiError(422, "no_file", "Choose a file to upload.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ApiError(413, "too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    try:
        mime, ext = storage.sniff(data, filename)
        pages, kind = storage.describe(data, mime)
    except storage.StorageError as e:
        raise ApiError(422, "bad_file", str(e))
    except Exception:
        raise ApiError(422, "bad_file", "This file could not be opened. Check that it is not damaged or password-protected.")
    sha, key = storage.put(call.tenant_id, data, ext)
    row = call.tx.one(
        "INSERT INTO files (tenant_id, sha256, filename, mime, size_bytes, page_count, doc_kind, storage_key)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING id, sha256, filename, mime, size_bytes, page_count, doc_kind, created_at",
        call.tenant_id, sha, filename, mime, len(data), pages, kind, key)
    call.tx.event("FILE_UPLOADED", "files", str(row["id"]), filename, {"sha256": sha, "bytes": len(data)})
    return row


@endpoint(auth="tenant_user")
def file_content(call: Call):
    f = call.tx.one("SELECT * FROM files WHERE id = %s::uuid", call.path["file_id"])
    if not f:
        raise not_found("File")
    try:
        path = storage.verify(f["storage_key"], f["sha256"])
    except storage.StorageError as e:
        raise ApiError(409, "integrity", str(e))
    call.tx.event("FILE_DOWNLOADED", "files", str(f["id"]), f["filename"], {"sha256": f["sha256"]})
    disp = "inline" if call.query.get("inline") == "1" else "attachment"
    safe = re.sub(r'[^\w.\- ()]', "_", f["filename"])
    return FileResponse(path, media_type=f["mime"], headers={"Content-Disposition": f'{disp}; filename="{safe}"'})


# ------------------------------------------------------------------ products
class ProductIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    strengths: str | None = Field(default=None, max_length=200)
    dosage_form: str | None = Field(default=None, max_length=120)
    registration_no: str | None = Field(default=None, max_length=80)
    markets: list[str] = Field(default_factory=list, max_length=60)
    gtin: str | None = Field(default=None, pattern=r"^\s*([0-9]{8,14})?\s*$")
    _c = field_validator("code")(_code)

    _m = field_validator("markets")(lambda v: _markets(v))


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    strengths: str | None = Field(default=None, max_length=200)
    dosage_form: str | None = Field(default=None, max_length=120)
    registration_no: str | None = Field(default=None, max_length=80)
    markets: list[str] | None = None
    gtin: str | None = Field(default=None, pattern=r"^\s*([0-9]{8,14})?\s*$")
    active: bool | None = None


PRODUCT_SQL = """
SELECT p.*, (SELECT count(*) FROM components c WHERE c.product_id = p.id AND c.active) AS component_count,
       (SELECT count(*) FROM artwork_versions a JOIN components c ON c.id = a.component_id
         WHERE c.product_id = p.id AND a.status = 'effective') AS effective_count
  FROM products p
"""


@endpoint(auth="tenant_user")
def list_products(call: Call):
    q = (call.query.get("q") or "").strip()
    where, params = [], []
    if q:
        where.append("(p.code ILIKE %s OR p.name ILIKE %s OR p.generic_name ILIKE %s OR p.name_ar ILIKE %s)")
        params += [f"%{q}%"] * 4
    if call.query.get("active") != "all":
        where.append("p.active")
    sql = PRODUCT_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY p.code"
    return {"items": call.tx.q(sql, *params), "can_edit": can_edit_library(call)}


@endpoint(auth="tenant_user", body=ProductIn)
def create_product(call: Call):
    require_library_edit(call)
    b: ProductIn = call.body
    if call.tx.val("SELECT 1 FROM products WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    row = call.tx.one(
        "INSERT INTO products (tenant_id, code, name, name_ar, generic_name, strengths, dosage_form, registration_no,"
        " markets, gtin) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        call.tenant_id, b.code, b.name.strip(), _opt(b.name_ar), _opt(b.generic_name), _opt(b.strengths),
        _opt(b.dosage_form), _opt(b.registration_no), b.markets, _opt(b.gtin))
    return _product(call, row["id"])


def _opt(v):
    return (v or "").strip() or None


@endpoint(auth="tenant_user", body=ProductPatch)
def update_product(call: Call):
    require_library_edit(call)
    pid = call.path["product_id"]
    _product(call, pid)
    b: ProductPatch = call.body
    for col in ("name", "name_ar", "generic_name", "strengths", "dosage_form", "registration_no", "gtin", "active"):
        val = getattr(b, col)
        if val is not None:
            call.tx.x(f"UPDATE products SET {col} = %s WHERE id = %s::uuid", val if col == "active" else _opt(val), pid)
    if b.markets is not None:
        try:
            markets = _markets(b.markets)
        except ValueError as e:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"markets": str(e)})
        call.tx.x("UPDATE products SET markets = %s WHERE id = %s::uuid", markets, pid)
    return _product(call, pid)


def _product(call: Call, pid) -> dict:
    p = call.tx.one(PRODUCT_SQL + " WHERE p.id = %s::uuid", str(pid))
    if not p:
        raise not_found("Product")
    p["components"] = call.tx.q(
        "SELECT c.*, (SELECT json_build_object('id', a.id, 'version', a.version, 'effective_from', a.effective_from)"
        "               FROM artwork_versions a WHERE a.component_id = c.id AND a.status = 'effective') AS effective"
        "  FROM components c WHERE c.product_id = %s::uuid ORDER BY c.active DESC, c.kind, c.code", str(pid))
    p["can_edit"] = can_edit_library(call)
    return p


@endpoint(auth="tenant_user")
def get_product(call: Call):
    return _product(call, call.path["product_id"])


# ------------------------------------------------------------------ components
class ComponentIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    kind: Literal["leaflet", "carton", "label", "sachet", "blister_foil", "tube", "other"]
    name: str = Field(min_length=1, max_length=200)
    languages: list[Literal["en", "ar"]] = Field(default_factory=lambda: ["en", "ar"], min_length=1)
    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    notes: str | None = Field(default=None, max_length=1000)
    _c = field_validator("code")(_code)


class ComponentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    languages: list[Literal["en", "ar"]] | None = None
    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{0,2}$")
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


@endpoint(auth="tenant_user", body=ComponentIn)
def create_component(call: Call):
    require_library_edit(call)
    pid = call.path["product_id"]
    _product(call, pid)
    b: ComponentIn = call.body
    if call.tx.val("SELECT 1 FROM components WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    row = call.tx.one(
        "INSERT INTO components (tenant_id, product_id, code, kind, name, languages, market, notes)"
        " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s) RETURNING id",
        call.tenant_id, pid, b.code, b.kind, b.name.strip(), sorted(set(b.languages)),
        b.market.upper() if b.market else None, _opt(b.notes))
    return _component(call, row["id"])


@endpoint(auth="tenant_user", body=ComponentPatch)
def update_component(call: Call):
    require_library_edit(call)
    cid = call.path["component_id"]
    _component(call, cid)
    b: ComponentPatch = call.body
    if b.name is not None:
        call.tx.x("UPDATE components SET name = %s WHERE id = %s::uuid", b.name.strip(), cid)
    if b.languages is not None:
        if not b.languages:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"languages": "Choose at least one language."})
        call.tx.x("UPDATE components SET languages = %s WHERE id = %s::uuid", sorted(set(b.languages)), cid)
    if b.market is not None:
        call.tx.x("UPDATE components SET market = %s WHERE id = %s::uuid", b.market.upper() or None, cid)
    if b.notes is not None:
        call.tx.x("UPDATE components SET notes = %s WHERE id = %s::uuid", _opt(b.notes), cid)
    if b.active is not None:
        call.tx.x("UPDATE components SET active = %s WHERE id = %s::uuid", b.active, cid)
    return _component(call, cid)


ARTWORK_SQL = """
SELECT a.*, f.filename, f.sha256, f.page_count, f.doc_kind, f.size_bytes, u.full_name AS created_by_name
  FROM artwork_versions a JOIN files f ON f.id = a.file_id LEFT JOIN users u ON u.id = a.created_by
"""


def _component(call: Call, cid) -> dict:
    c = call.tx.one("SELECT c.*, p.code AS product_code, p.name AS product_name FROM components c"
                    " JOIN products p ON p.id = c.product_id WHERE c.id = %s::uuid", str(cid))
    if not c:
        raise not_found("Packaging component")
    versions = call.tx.q(ARTWORK_SQL + " WHERE a.component_id = %s::uuid ORDER BY a.created_at DESC", str(cid))
    for v in versions:
        v["signatures"] = esign.list_for(call, "artwork_version", str(v["id"]))
    c["versions"] = versions
    shades = call.tx.q(SHADE_SQL + " WHERE s.component_id = %s::uuid ORDER BY s.created_at DESC", str(cid))
    for sh in shades:
        sh["signatures"] = esign.list_for(call, "shade_set", str(sh["id"]))
        sh["measurement"] = _public_measurement(sh["measurement"])
    c["shade_sets"] = shades
    c["can_edit"] = can_edit_library(call)
    return c


@endpoint(auth="tenant_user")
def get_component(call: Call):
    return _component(call, call.path["component_id"])


@endpoint(auth="tenant_user")
def list_components(call: Call):
    """Flat list for pickers: active components with their effective artwork."""
    return {"items": call.tx.q(
        "SELECT c.id, c.code, c.kind, c.name, c.languages, p.id AS product_id, p.code AS product_code, p.name AS product_name,"
        "       a.id AS artwork_id, a.version AS artwork_version, a.file_id AS artwork_file_id, f.filename AS artwork_filename,"
        "       sh.id AS shade_set_id, sh.version AS shade_version, sh.source AS shade_source"
        "  FROM components c JOIN products p ON p.id = c.product_id"
        "  LEFT JOIN artwork_versions a ON a.component_id = c.id AND a.status = 'effective'"
        "  LEFT JOIN shade_sets sh ON sh.component_id = c.id AND sh.status = 'effective'"
        "  LEFT JOIN files f ON f.id = a.file_id"
        " WHERE c.active AND p.active ORDER BY p.code, c.kind, c.code")}


# ------------------------------------------------------------------ artwork versions
class ArtworkIn(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,20}$")
    file_id: str
    effective_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    change_control: str | None = Field(default=None, max_length=80)
    authority_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


@endpoint(auth="tenant_user", body=ArtworkIn)
def create_artwork(call: Call):
    require_library_edit(call)
    cid = call.path["component_id"]
    _component(call, cid)
    b: ArtworkIn = call.body
    if not call.tx.val("SELECT 1 FROM files WHERE id = %s::uuid", b.file_id):
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"file_id": "Upload the approved artwork file."})
    if call.tx.val("SELECT 1 FROM artwork_versions WHERE component_id = %s::uuid AND version = %s", cid, b.version):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"version": "This version already exists."})
    call.tx.x("INSERT INTO artwork_versions (tenant_id, component_id, version, file_id, effective_from, change_control,"
              " authority_ref, notes) VALUES (%s, %s::uuid, %s, %s::uuid, %s::date, %s, %s, %s)",
              call.tenant_id, cid, b.version, b.file_id, b.effective_from, _opt(b.change_control),
              _opt(b.authority_ref), _opt(b.notes))
    return _component(call, cid)


class ArtworkSignIn(BaseModel):
    meaning: Literal["approved_master", "withdrawn"]
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=500)


@endpoint(auth="tenant_user", body=ArtworkSignIn)
def sign_artwork(call: Call):
    b: ArtworkSignIn = call.body
    require_signer(call, "approver")
    a = call.tx.one(ARTWORK_SQL + " WHERE a.id = %s::uuid", call.path["artwork_id"])
    if not a:
        raise not_found("Artwork version")
    comp = call.tx.one("SELECT code FROM components WHERE id = %s", a["component_id"])
    label = f"{comp['code']} v{a['version']}"
    if b.meaning == "approved_master" and a["status"] != "draft":
        raise ApiError(409, "not_draft", "Only a draft version can be approved as the master.")
    if b.meaning == "withdrawn":
        if a["status"] not in ("draft", "effective"):
            raise ApiError(409, "closed", "This version is already closed.")
        if not (b.reason or "").strip():
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"reason": "Give the reason for withdrawal."})
    esign.sign(call, entity="artwork_version", record_id=str(a["id"]), label=label, meaning=b.meaning,
               record_hash=a["sha256"], email=b.email, password=b.password, reason=b.reason)
    if b.meaning == "approved_master":
        call.tx.x("UPDATE artwork_versions SET status = 'superseded' WHERE component_id = %s AND status = 'effective'",
                  a["component_id"])
        call.tx.x("UPDATE artwork_versions SET status = 'effective', effective_from = coalesce(effective_from, current_date)"
                  " WHERE id = %s", a["id"])
    else:
        call.tx.x("UPDATE artwork_versions SET status = 'withdrawn' WHERE id = %s", a["id"])
    return _component(call, a["component_id"])



# ------------------------------------------------------------------ shade sets (colour references)
SHADE_SQL = """
SELECT s.*, u.full_name AS created_by_name,
       fs.filename AS standard_filename, fl.filename AS light_filename, fd.filename AS dark_filename
  FROM shade_sets s JOIN files fs ON fs.id = s.standard_file_id JOIN files fl ON fl.id = s.light_file_id
  JOIN files fd ON fd.id = s.dark_file_id LEFT JOIN users u ON u.id = s.created_by
"""


def _public_measurement(m: dict) -> dict:
    """The measurement without the sample point lists (large and of no use to the browser)."""
    m = dict(m or {})
    m["inks"] = [{k: v for k, v in i.items() if k != "points"} for i in m.get("inks", [])]
    return m


def shade_dir(tenant_id: str, shade_id: str) -> str:
    import os
    return os.path.join(storage.root(), "tenants", str(tenant_id), "shades", str(shade_id))


def measurement_sha(m: dict) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class ShadeIn(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,20}$")
    source: Literal["scan_target", "scan", "spectro", "photo"]
    standard_file_id: str
    light_file_id: str
    dark_file_id: str
    supplier: str | None = Field(default=None, max_length=120)
    reference_no: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)


@endpoint(auth="tenant_user", body=ShadeIn)
def create_shade_set(call: Call):
    """Measure the three shade cards, verify Light > Standard > Dark per ink, and register a draft reference."""
    import hashlib
    import json
    import os
    import uuid
    from ..engine import colour
    require_library_edit(call)
    cid = call.path["component_id"]
    _component(call, cid)
    b: ShadeIn = call.body
    ids = {"standard": b.standard_file_id, "light": b.light_file_id, "dark": b.dark_file_id}
    if len(set(ids.values())) < 3:
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"light_file_id": "Standard, Light and Dark must be three different files."})
    if call.tx.val("SELECT 1 FROM shade_sets WHERE component_id = %s::uuid AND version = %s", cid, b.version):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"version": "This version already exists."})
    paths, kinds = {}, {}
    for tag, fid in ids.items():
        f = call.tx.one("SELECT storage_key, sha256, doc_kind FROM files WHERE id = %s::uuid", fid)
        if not f:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={f"{tag}_file_id": "Upload this file."})
        try:
            paths[tag] = storage.verify(f["storage_key"], f["sha256"])
        except storage.StorageError as e:
            raise ApiError(409, "integrity", str(e))
        kinds[tag] = f["doc_kind"]
    spectro = None
    if b.source == "spectro":
        if any(k != "spectro" for k in kinds.values()):
            raise ApiError(422, "invalid", "Some fields need attention.",
                           fields={"source": "Upload three spectrophotometer files (CxF or CGATS) for this source."})
        spectro = {}
        for tag, p in paths.items():
            with open(p, "rb") as fh:
                spectro[tag] = colour.parse_spectro(fh.read())
    elif any(k == "spectro" for k in kinds.values()):
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"source": "These are measurement files: choose “Spectrophotometer” as the source."})
    try:
        m = colour.analyse_set(b.source, paths.get("standard"), paths.get("light"), paths.get("dark"), spectro)
    except colour.ColourError as e:
        raise ApiError(422, "colour", str(e))
    images = m.pop("_images", None)
    sid = str(uuid.uuid4())
    if images:
        d = shade_dir(call.tenant_id, sid)
        os.makedirs(d, exist_ok=True)
        m["previews"] = {}
        for tag, img in images.items():
            data = colour.to_jpeg(colour.outline_inks(img, m["inks"]))
            with open(os.path.join(d, f"{tag}.jpg"), "wb") as fh:
                fh.write(data)
            m["previews"][tag] = hashlib.sha256(data).hexdigest()
    m["files"] = {tag: call.tx.val("SELECT sha256 FROM files WHERE id = %s::uuid", fid) for tag, fid in ids.items()}
    sha = measurement_sha(m)
    call.tx.x("INSERT INTO shade_sets (id, tenant_id, component_id, version, source, standard_file_id, light_file_id,"
              " dark_file_id, measurement, measurement_sha256, verification, supplier, reference_no, notes)"
              " VALUES (%s::uuid, %s, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s::uuid, %s::jsonb, %s, %s, %s, %s, %s)",
              sid, call.tenant_id, cid, b.version, b.source, b.standard_file_id, b.light_file_id, b.dark_file_id,
              json.dumps(m, ensure_ascii=False), sha, m["verification"], _opt(b.supplier), _opt(b.reference_no),
              _opt(b.notes))
    return _component(call, cid)


@endpoint(auth="tenant_user")
def shade_preview(call: Call):
    import os
    which = call.path["which"]
    if which not in ("standard", "light", "dark"):
        raise not_found("Preview")
    s = call.tx.one("SELECT id, tenant_id, measurement FROM shade_sets WHERE id = %s::uuid", call.path["shade_id"])
    if not s:
        raise not_found("Shade set")
    want = (s["measurement"].get("previews") or {}).get(which)
    p = os.path.join(shade_dir(s["tenant_id"], s["id"]), f"{which}.jpg")
    if not want or not os.path.exists(p):
        raise not_found("Preview")
    import hashlib
    with open(p, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != want:
            raise ApiError(409, "integrity", "The preview no longer matches its recorded SHA-256.")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class ShadeSignIn(BaseModel):
    meaning: Literal["approved_master", "withdrawn"]
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=500)


@endpoint(auth="tenant_user", body=ShadeSignIn)
def sign_shade_set(call: Call):
    b: ShadeSignIn = call.body
    require_signer(call, "approver")
    s = call.tx.one(SHADE_SQL + " WHERE s.id = %s::uuid", call.path["shade_id"])
    if not s:
        raise not_found("Shade set")
    comp = call.tx.one("SELECT code FROM components WHERE id = %s", s["component_id"])
    label = f"{comp['code']} shades {s['version']}"
    if b.meaning == "approved_master":
        if s["status"] != "draft":
            raise ApiError(409, "not_draft", "Only a draft shade set can be approved as the reference.")
        if s["verification"] == "fail":
            raise ApiError(409, "verification_failed", "This shade set failed the Light / Standard / Dark check and "
                           "cannot be approved. Check the card labels and register the scans again.")
    else:
        if s["status"] not in ("draft", "effective"):
            raise ApiError(409, "closed", "This shade set is already closed.")
        if not (b.reason or "").strip():
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"reason": "Give the reason for withdrawal."})
    esign.sign(call, entity="shade_set", record_id=str(s["id"]), label=label, meaning=b.meaning,
               record_hash=s["measurement_sha256"], email=b.email, password=b.password, reason=b.reason)
    if b.meaning == "approved_master":
        call.tx.x("UPDATE shade_sets SET status = 'superseded' WHERE component_id = %s AND status = 'effective'",
                  s["component_id"])
        call.tx.x("UPDATE shade_sets SET status = 'effective' WHERE id = %s", s["id"])
    else:
        call.tx.x("UPDATE shade_sets SET status = 'withdrawn' WHERE id = %s", s["id"])
    return _component(call, s["component_id"])
