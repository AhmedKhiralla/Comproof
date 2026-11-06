"""Platform administration: companies (tenants) and their first administrators."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..api import ApiError, Call, endpoint, not_found
from ..defaults import effective_features
from ..security import DEFAULT_POLICY, hash_password, temporary_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address.")
    return v


class AdminIn(BaseModel):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=1, max_length=120)
    _e = field_validator("email")(_email)


class TenantCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=1, max_length=160)
    country: str = Field(default="EG", min_length=2, max_length=2)
    timezone: str = Field(default="Africa/Cairo", max_length=64)
    default_language: Literal["en", "ar"] = "en"
    admin: AdminIn

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9_-]{1,19}$", v):
            raise ValueError("Use 2–20 letters, digits, dash or underscore.")
        return v

    @field_validator("country")
    @classmethod
    def _country(cls, v: str) -> str:
        return v.strip().upper()


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    default_language: Literal["en", "ar"] | None = None
    status: Literal["active", "suspended"] | None = None


TENANT_LIST_SQL = """
SELECT t.id, t.code, t.name, t.country, t.timezone, t.default_language, t.status, t.created_at,
       (SELECT count(*) FROM sites s WHERE s.tenant_id = t.id) AS site_count,
       (SELECT count(*) FROM users u WHERE u.tenant_id = t.id) AS user_count
  FROM tenants t
"""


@endpoint(auth="platform")
def list_tenants(call: Call):
    return {"items": call.tx.q(TENANT_LIST_SQL + " ORDER BY t.code")}


def _create_user(call: Call, tenant_id: str, admin: AdminIn) -> tuple[dict, str]:
    temp = temporary_password(DEFAULT_POLICY)
    user = call.tx.one(
        "INSERT INTO users (tenant_id, email, full_name, password_hash, is_tenant_admin, must_change_password)"
        " VALUES (%s, %s, %s, %s, true, true) RETURNING id, email, full_name",
        tenant_id, admin.email, admin.full_name.strip(), hash_password(temp))
    return user, temp


@endpoint(auth="platform", body=TenantCreate)
def create_tenant(call: Call):
    b: TenantCreate = call.body
    tx = call.tx
    if tx.val("SELECT 1 FROM tenants WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    if tx.val("SELECT 1 FROM users WHERE lower(email) = %s", b.admin.email):
        raise ApiError(409, "duplicate", "Some fields need attention.",
                       fields={"admin.email": "A user with this email already exists."})
    tenant = tx.one(
        "INSERT INTO tenants (code, name, country, timezone, default_language, features, security)"
        " VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING id, code, name",
        b.code, b.name.strip(), b.country, b.timezone, b.default_language,
        json.dumps(effective_features(None)), json.dumps(DEFAULT_POLICY))
    user, temp = _create_user(call, str(tenant["id"]), b.admin)
    return {"tenant": tenant, "admin": user, "temporary_password": temp}


@endpoint(auth="platform", body=TenantUpdate)
def update_tenant(call: Call):
    b: TenantUpdate = call.body
    tid = call.path["tenant_id"]
    if not call.tx.val("SELECT 1 FROM tenants WHERE id = %s::uuid", tid):
        raise not_found("Company")
    for col in ("name", "country", "timezone", "default_language", "status"):
        val = getattr(b, col)
        if val is not None:
            if col == "country":
                val = val.upper()
            call.tx.x(f"UPDATE tenants SET {col} = %s WHERE id = %s::uuid", val, tid)
    if b.status == "suspended":
        call.tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'tenant_suspended'"
                  " WHERE tenant_id = %s::uuid AND revoked_at IS NULL", tid)
    return call.tx.one(TENANT_LIST_SQL + " WHERE t.id = %s::uuid", tid)


@endpoint(auth="platform")
def list_tenant_admins(call: Call):
    tid = call.path["tenant_id"]
    return {"items": call.tx.q(
        "SELECT id, email, full_name, status, must_change_password, last_login_at, locked_until"
        "  FROM users WHERE tenant_id = %s::uuid AND is_tenant_admin ORDER BY full_name", tid)}


@endpoint(auth="platform", body=AdminIn)
def create_tenant_admin(call: Call):
    tid = call.path["tenant_id"]
    if not call.tx.val("SELECT 1 FROM tenants WHERE id = %s::uuid", tid):
        raise not_found("Company")
    if call.tx.val("SELECT 1 FROM users WHERE lower(email) = %s", call.body.email):
        raise ApiError(409, "duplicate", "Some fields need attention.",
                       fields={"email": "A user with this email already exists."})
    user, temp = _create_user(call, tid, call.body)
    return {"admin": user, "temporary_password": temp}


@endpoint(auth="platform")
def reset_tenant_admin_password(call: Call):
    uid = call.path["user_id"]
    user = call.tx.one("SELECT id, email, tenant_id FROM users WHERE id = %s::uuid AND is_tenant_admin", uid)
    if not user:
        raise not_found("Administrator")
    temp = temporary_password(DEFAULT_POLICY)
    call.tx.x("UPDATE users SET password_hash = %s, must_change_password = true, password_changed_at = now(),"
              " failed_attempts = 0, locked_until = NULL WHERE id = %s", hash_password(temp), user["id"])
    call.tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'password_reset'"
              " WHERE user_id = %s AND revoked_at IS NULL", user["id"])
    call.tx.event("PASSWORD_RESET", "users", str(user["id"]), user["email"], tenant_id=str(user["tenant_id"]))
    return {"temporary_password": temp}
