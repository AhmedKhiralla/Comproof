"""Company administration: sites, users, site roles and company settings."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..api import ApiError, Call, endpoint, not_found
from ..defaults import FEATURES, TERMS, effective_engine, effective_features, effective_terms
from ..engine import ai
from ..security import POLICY_LIMITS, effective_policy, hash_password, temporary_password
from .platform import _email

ROLES = ("artwork_editor", "reviewer", "approver", "viewer")


# ------------------------------------------------------------------ sites
class SiteIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=160)
    country: str = Field(default="EG", min_length=2, max_length=2)
    timezone: str = Field(default="Africa/Cairo", max_length=64)
    address: str | None = Field(default=None, max_length=400)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9_-]{0,19}$", v):
            raise ValueError("Use up to 20 letters, digits, dash or underscore.")
        return v


class SitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=400)
    active: bool | None = None


SITE_SQL = """
SELECT s.id, s.code, s.name, s.country, s.timezone, s.address, s.active, s.updated_at,
       (SELECT count(DISTINCT r.user_id) FROM user_site_roles r WHERE r.site_id = s.id) AS user_count
  FROM sites s
"""


@endpoint(auth="tenant_admin")
def list_sites(call: Call):
    return {"items": call.tx.q(SITE_SQL + " ORDER BY s.active DESC, s.code")}


@endpoint(auth="tenant_admin", body=SiteIn)
def create_site(call: Call):
    b: SiteIn = call.body
    if call.tx.val("SELECT 1 FROM sites WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    row = call.tx.one(
        "INSERT INTO sites (tenant_id, code, name, country, timezone, address)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        call.tenant_id, b.code, b.name.strip(), b.country.upper(), b.timezone, (b.address or "").strip() or None)
    return call.tx.one(SITE_SQL + " WHERE s.id = %s", row["id"])


@endpoint(auth="tenant_admin", body=SitePatch)
def update_site(call: Call):
    sid = call.path["site_id"]
    if not call.tx.val("SELECT 1 FROM sites WHERE id = %s::uuid", sid):
        raise not_found("Site")
    b: SitePatch = call.body
    for col in ("name", "country", "timezone", "address", "active"):
        val = getattr(b, col)
        if val is not None:
            if col == "country":
                val = val.upper()
            if col == "address":
                val = val.strip() or None
            call.tx.x(f"UPDATE sites SET {col} = %s WHERE id = %s::uuid", val, sid)
    return call.tx.one(SITE_SQL + " WHERE s.id = %s::uuid", sid)


# ------------------------------------------------------------------ users
class RoleIn(BaseModel):
    site_id: str
    role: Literal["artwork_editor", "reviewer", "approver", "viewer"]


class UserIn(BaseModel):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=1, max_length=120)
    is_tenant_admin: bool = False
    roles: list[RoleIn] = Field(default_factory=list)
    _e = field_validator("email")(_email)


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_tenant_admin: bool | None = None
    status: Literal["active", "disabled"] | None = None


class RolesIn(BaseModel):
    roles: list[RoleIn]


USER_SQL = """
SELECT u.id, u.email, u.full_name, u.is_tenant_admin, u.status, u.must_change_password,
       u.last_login_at, u.locked_until, u.created_at,
       coalesce((SELECT json_agg(json_build_object('site_id', r.site_id, 'role', r.role) ORDER BY r.role)
                   FROM user_site_roles r WHERE r.user_id = u.id), '[]'::json) AS roles,
       (u.locked_until IS NOT NULL AND u.locked_until > now()) AS is_locked
  FROM users u
"""


def _user(call: Call, uid) -> dict:
    row = call.tx.one(USER_SQL + " WHERE u.id = %s::uuid", str(uid))
    if not row:
        raise not_found("User")
    return row


@endpoint(auth="tenant_admin")
def list_users(call: Call):
    return {"items": call.tx.q(USER_SQL + " ORDER BY u.status, u.full_name")}


def _set_roles(call: Call, uid: str, roles: list[RoleIn]) -> None:
    wanted = {(r.site_id, r.role) for r in roles}
    site_ids = {s for s, _ in wanted}
    if site_ids:
        found = {str(r["id"]) for r in call.tx.q("SELECT id FROM sites WHERE active")}
        missing = site_ids - found
        if missing:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"roles": "Unknown or inactive site."})
    current = {(str(r["site_id"]), r["role"]): r["id"]
               for r in call.tx.q("SELECT id, site_id, role FROM user_site_roles WHERE user_id = %s::uuid", uid)}
    for key, rid in current.items():
        if key not in wanted:
            call.tx.x("DELETE FROM user_site_roles WHERE id = %s", rid)
    for site_id, role in wanted - set(current):
        call.tx.x("INSERT INTO user_site_roles (tenant_id, user_id, site_id, role) VALUES (%s, %s::uuid, %s::uuid, %s)",
                  call.tenant_id, uid, site_id, role)


@endpoint(auth="tenant_admin", body=UserIn)
def create_user(call: Call):
    b: UserIn = call.body
    if call.tx.val("SELECT 1 FROM users WHERE lower(email) = %s", b.email) or \
            call.tx.val("SELECT cp_email_taken(%s)", b.email):
        raise ApiError(409, "duplicate", "Some fields need attention.",
                       fields={"email": "A user with this email already exists."})
    temp = temporary_password(call.policy)
    row = call.tx.one(
        "INSERT INTO users (tenant_id, email, full_name, password_hash, is_tenant_admin, must_change_password)"
        " VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
        call.tenant_id, b.email, b.full_name.strip(), hash_password(temp), b.is_tenant_admin)
    _set_roles(call, str(row["id"]), b.roles)
    return {"user": _user(call, row["id"]), "temporary_password": temp}


@endpoint(auth="tenant_admin", body=UserPatch)
def update_user(call: Call):
    uid = call.path["user_id"]
    user = _user(call, uid)
    b: UserPatch = call.body
    is_self = str(user["id"]) == str(call.user["id"])
    if is_self and (b.status == "disabled" or b.is_tenant_admin is False):
        raise ApiError(422, "self_change", "You cannot disable your own account or remove your own administrator access.")
    if b.full_name is not None:
        call.tx.x("UPDATE users SET full_name = %s WHERE id = %s::uuid", b.full_name.strip(), uid)
    if b.is_tenant_admin is not None:
        call.tx.x("UPDATE users SET is_tenant_admin = %s WHERE id = %s::uuid", b.is_tenant_admin, uid)
    if b.status is not None:
        call.tx.x("UPDATE users SET status = %s WHERE id = %s::uuid", b.status, uid)
        if b.status == "disabled":
            call.tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'disabled'"
                      " WHERE user_id = %s::uuid AND revoked_at IS NULL", uid)
    if b.is_tenant_admin is False or b.status == "disabled":
        remaining = call.tx.val("SELECT count(*) FROM users WHERE is_tenant_admin AND status = 'active'")
        if remaining == 0:
            raise ApiError(422, "last_admin", "The company must keep at least one active administrator.")
    return _user(call, uid)


@endpoint(auth="tenant_admin", body=RolesIn)
def set_user_roles(call: Call):
    uid = call.path["user_id"]
    _user(call, uid)
    _set_roles(call, uid, call.body.roles)
    return _user(call, uid)


@endpoint(auth="tenant_admin")
def reset_user_password(call: Call):
    uid = call.path["user_id"]
    user = _user(call, uid)
    temp = temporary_password(call.policy)
    call.tx.x("UPDATE users SET password_hash = %s, must_change_password = true, password_changed_at = now(),"
              " failed_attempts = 0, locked_until = NULL WHERE id = %s::uuid", hash_password(temp), uid)
    call.tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'password_reset'"
              " WHERE user_id = %s::uuid AND revoked_at IS NULL", uid)
    call.tx.event("PASSWORD_RESET", "users", str(uid), user["email"])
    return {"temporary_password": temp}


@endpoint(auth="tenant_admin")
def unlock_user(call: Call):
    uid = call.path["user_id"]
    user = _user(call, uid)
    call.tx.x("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s::uuid", uid)
    call.tx.event("UNLOCKED", "users", str(uid), user["email"])
    return _user(call, uid)


# ------------------------------------------------------------------ settings
@endpoint(auth="tenant_admin")
def get_settings(call: Call):
    t = call.tx.one("SELECT id, code, name, country, timezone, default_language, features, terminology, security, engine"
                    " FROM tenants WHERE id = %s", call.tenant_id)
    return {
        "company": {k: t[k] for k in ("id", "code", "name", "country", "timezone", "default_language")},
        "features": effective_features(t["features"]),
        "feature_groups": {k: v["group"] for k, v in FEATURES.items()},
        "engine": effective_engine(t["engine"]),
        "ai_providers": ai.available(),
        "terminology": effective_terms(t["terminology"]),
        "terminology_defaults": TERMS,
        "security": effective_policy(t["security"]),
        "security_limits": POLICY_LIMITS,
    }


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    default_language: Literal["en", "ar"] | None = None


@endpoint(auth="tenant_admin", body=CompanyPatch)
def update_company(call: Call):
    b: CompanyPatch = call.body
    for col in ("name", "country", "timezone", "default_language"):
        val = getattr(b, col)
        if val is not None:
            call.tx.x(f"UPDATE tenants SET {col} = %s WHERE id = %s", val.upper() if col == "country" else val,
                      call.tenant_id)
    return get_settings.__wrapped__(call)


class FeaturesIn(BaseModel):
    features: dict[str, bool]


@endpoint(auth="tenant_admin", body=FeaturesIn)
def update_features(call: Call):
    unknown = set(call.body.features) - set(FEATURES)
    if unknown:
        raise ApiError(422, "invalid", "Unknown feature: " + ", ".join(sorted(unknown)))
    merged = effective_features(call.tx.val("SELECT features FROM tenants WHERE id = %s", call.tenant_id))
    merged.update(call.body.features)
    call.tx.x("UPDATE tenants SET features = %s::jsonb WHERE id = %s", json.dumps(merged), call.tenant_id)
    return get_settings.__wrapped__(call)


class TermsIn(BaseModel):
    terminology: dict[str, dict[str, str]]


@endpoint(auth="tenant_admin", body=TermsIn)
def update_terminology(call: Call):
    clean: dict[str, dict[str, str]] = {}
    for key, langs in call.body.terminology.items():
        if key not in TERMS:
            raise ApiError(422, "invalid", f"Unknown term: {key}")
        entry = {}
        for lang in ("en", "ar"):
            val = (langs.get(lang) or "").strip()
            if len(val) > 60:
                raise ApiError(422, "invalid", "Some fields need attention.", fields={f"{key}.{lang}": "Use 60 characters or fewer."})
            if val and val != TERMS[key][lang]:
                entry[lang] = val
        if entry:
            clean[key] = entry
    call.tx.x("UPDATE tenants SET terminology = %s::jsonb WHERE id = %s", json.dumps(clean), call.tenant_id)
    return get_settings.__wrapped__(call)


class SecurityIn(BaseModel):
    min_length: int
    require_upper: bool
    require_lower: bool
    require_digit: bool
    require_symbol: bool
    expiry_days: int
    history: int
    max_failed_attempts: int
    lockout_minutes: int
    session_timeout_minutes: int


@endpoint(auth="tenant_admin", body=SecurityIn)
def update_security(call: Call):
    data = call.body.model_dump()
    fields = {}
    for key, (lo, hi) in POLICY_LIMITS.items():
        if not lo <= data[key] <= hi:
            fields[key] = f"Use a value from {lo} to {hi}."
    if fields:
        raise ApiError(422, "invalid", "Some fields need attention.", fields=fields)
    call.tx.x("UPDATE tenants SET security = %s::jsonb WHERE id = %s", json.dumps(data), call.tenant_id)
    return get_settings.__wrapped__(call)


class EngineIn(BaseModel):
    provider: str | None = Field(default=None, max_length=40)
    reading_provider: str | None = Field(default=None, max_length=40)
    exclude_phrases: list[str] = Field(default_factory=list, max_length=200)
    rotated_text: Literal["auto", "ignore", "read"] = "auto"


@endpoint(auth="tenant_admin", body=EngineIn)
def update_engine(call: Call):
    b: EngineIn = call.body
    names = {p["name"] for p in ai.available()}
    for key in ("provider", "reading_provider"):
        val = getattr(b, key)
        if val and val not in names:
            raise ApiError(422, "invalid", "Some fields need attention.", fields={key: "This AI provider is not configured on the server."})
    phrases = sorted({p.strip()[:200] for p in b.exclude_phrases if p.strip()})
    data = {"provider": b.provider or None, "reading_provider": b.reading_provider or None,
            "exclude_phrases": phrases, "rotated_text": b.rotated_text}
    call.tx.x("UPDATE tenants SET engine = %s::jsonb WHERE id = %s", json.dumps(data), call.tenant_id)
    return get_settings.__wrapped__(call)
