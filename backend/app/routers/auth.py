"""Sign-in, sign-out, current user, password change and personal preferences."""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from pydantic import BaseModel, Field

from .. import db
from ..api import SESSION_COOKIE, ApiError, Call, endpoint
from ..config import settings
from ..defaults import effective_features, effective_terms
from ..engine.ai import status as ai_status
from ..security import (DUMMY_HASH, effective_policy, hash_password, new_session_token,
                        password_problems, verify_password)

USER_SQL = """
SELECT u.*, t.status AS tenant_status, t.security AS tenant_security, now() AS db_now
  FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id
 WHERE lower(u.email) = lower(%s)
"""


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@endpoint(auth=None, body=LoginBody)
def login(call: Call):
    tx = call.tx
    b: LoginBody = call.body
    tx.apply(db.SYSTEM)
    user = tx.one(USER_SQL, b.email.strip())
    generic = ApiError(401, "invalid_credentials", "The email or password is incorrect.")

    def fail(reason: str, err: ApiError, user_row: dict | None = None):
        tid = str(user_row["tenant_id"]) if user_row and user_row["tenant_id"] else None
        tx.event("LOGIN_FAILED", "users", str(user_row["id"]) if user_row else None, b.email.strip()[:254],
                 {"reason": reason, "ip": call.client_ip()}, tenant_id=tid,
                 user_id=str(user_row["id"]) if user_row else None,
                 user_name=user_row["full_name"] if user_row else "unknown")
        tx.commit()  # keep the audit entry even though the request fails
        tx.apply(db.SYSTEM)
        raise err

    if user is None:
        verify_password(b.password, DUMMY_HASH)
        fail("unknown_email", generic)

    policy = effective_policy(user["tenant_security"])
    now = user["db_now"]

    if user["locked_until"] and user["locked_until"] > now:
        minutes = max(1, int((user["locked_until"] - now).total_seconds() // 60) + 1)
        fail("locked", ApiError(423, "locked",
                                f"This account is locked after repeated failed sign-ins. Try again in {minutes} minutes or ask your administrator to unlock it.",
                                extra={"minutes": minutes}), user)

    if not verify_password(b.password, user["password_hash"]):
        attempts = user["failed_attempts"] + 1
        if attempts >= policy["max_failed_attempts"]:
            tx.x("UPDATE users SET failed_attempts = 0, locked_until = now() + make_interval(mins => %s) WHERE id = %s",
                 policy["lockout_minutes"], user["id"])
            tx.event("LOCKED", "users", str(user["id"]), user["email"],
                     {"minutes": policy["lockout_minutes"], "ip": call.client_ip()},
                     tenant_id=str(user["tenant_id"]) if user["tenant_id"] else None,
                     user_id=str(user["id"]), user_name=user["full_name"])
            fail("wrong_password", ApiError(423, "locked",
                                            f"This account is now locked for {policy['lockout_minutes']} minutes after {policy['max_failed_attempts']} failed sign-ins.",
                                            extra={"minutes": policy["lockout_minutes"]}), user)
        tx.x("UPDATE users SET failed_attempts = %s WHERE id = %s", attempts, user["id"])
        fail("wrong_password", generic, user)

    if user["status"] != "active":
        fail("disabled", ApiError(403, "disabled", "This account is disabled. Contact your administrator."), user)
    if user["tenant_id"] and user["tenant_status"] != "active":
        fail("tenant_suspended", ApiError(403, "suspended", "This company account is suspended. Contact Comp11 Labs."), user)

    expired = policy["expiry_days"] > 0 and \
        now - user["password_changed_at"] > dt.timedelta(days=policy["expiry_days"])
    tx.x("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = now(),"
         " must_change_password = must_change_password OR %s WHERE id = %s", expired, user["id"])

    token, token_h = new_session_token()
    tx.x("INSERT INTO sessions (token_hash, user_id, tenant_id, expires_at, ip, user_agent)"
         " VALUES (%s, %s, %s, now() + make_interval(hours => %s), %s, %s)",
         token_h, user["id"], user["tenant_id"], settings.session_max_hours, call.client_ip(),
         (call.request.headers.get("user-agent") or "")[:300])
    tx.event("LOGIN", "users", str(user["id"]), user["email"], {"ip": call.client_ip()},
             tenant_id=str(user["tenant_id"]) if user["tenant_id"] else None,
             user_id=str(user["id"]), user_name=user["full_name"])
    call.cookies_to_set.append((SESSION_COOKIE, token, settings.session_max_hours * 3600))
    return {"ok": True}


@endpoint(auth="user", allow_password_change=True)
def logout(call: Call):
    call.tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'logout' WHERE id = %s",
              call.user["session_id"])
    call.tx.event("LOGOUT", "users", str(call.user["id"]), call.user["email"])
    call.cookies_to_clear.append(SESSION_COOKIE)
    return {"ok": True}


def me_payload(call: Call) -> dict:
    tx, u = call.tx, call.user
    data = {
        "user": {
            "id": u["id"], "email": u["email"], "full_name": u["full_name"],
            "is_platform_admin": u["is_platform_admin"], "is_tenant_admin": u["is_tenant_admin"],
            "language": u["language"], "theme": u["theme"],
            "must_change_password": u["must_change_password"],
            "guide": u.get("guide") or {},
        },
        "policy": call.policy,
        "tenant": None,
        "sites": [],
    }
    if u["tenant_id"]:
        t = tx.one("SELECT id, code, name, country, timezone, default_language, features, terminology"
                   " FROM tenants WHERE id = %s", u["tenant_id"])
        data["tenant"] = {
            "id": t["id"], "code": t["code"], "name": t["name"], "country": t["country"],
            "timezone": t["timezone"], "default_language": t["default_language"],
            "features": effective_features(t["features"]),
            "terminology": effective_terms(t["terminology"]),
            "ai": ai_status(t["features"]),
        }
        # Administrators see every active site; everyone keeps the roles they actually hold there, so an
        # administrator who is also an approver can sign (signing rights never come from "admin" alone).
        sites = tx.q(
            "SELECT s.id, s.code, s.name, s.country, s.timezone, s.active,"
            "       coalesce(string_agg(r.role, ',' ORDER BY r.role), '') AS role_list"
            "  FROM sites s LEFT JOIN user_site_roles r ON r.site_id = s.id AND r.user_id = %s"
            " WHERE s.active GROUP BY s.id"
            " HAVING %s OR count(r.role) > 0 ORDER BY s.code", u["id"], bool(u["is_tenant_admin"]))
        for s in sites:
            roles = [x for x in s.pop("role_list").split(",") if x]
            s["roles"] = (["admin"] if u["is_tenant_admin"] else []) + roles
        data["sites"] = sites
    return data


@endpoint(auth="user", allow_password_change=True)
def me(call: Call):
    return me_payload(call)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@endpoint(auth="user", body=ChangePasswordBody, allow_password_change=True)
def change_password(call: Call):
    tx, b = call.tx, call.body
    row = tx.one("SELECT password_hash FROM users WHERE id = %s", call.user["id"])
    if not verify_password(b.current_password, row["password_hash"]):
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"current_password": "The current password is incorrect."})
    policy = call.policy
    problems = password_problems(b.new_password, policy)
    if problems:
        raise ApiError(422, "weak_password", "The new password does not meet the password policy.",
                       fields={"new_password": "policy"}, extra={"rules": problems})
    if verify_password(b.new_password, row["password_hash"]):
        raise ApiError(422, "reused_password", "Choose a password you have not used before.",
                       fields={"new_password": "reused"})
    if policy["history"] > 0:
        previous = tx.q("SELECT password_hash FROM password_history WHERE user_id = %s"
                        " ORDER BY created_at DESC LIMIT %s", call.user["id"], policy["history"])
        if any(verify_password(b.new_password, p["password_hash"]) for p in previous):
            raise ApiError(422, "reused_password",
                           f"Choose a password you have not used in your last {policy['history']} changes.",
                           fields={"new_password": "reused"})
    tx.x("INSERT INTO password_history (user_id, tenant_id, password_hash) VALUES (%s, %s, %s)",
         call.user["id"], call.user["tenant_id"], row["password_hash"])
    tx.x("UPDATE users SET password_hash = %s, password_changed_at = now(), must_change_password = false"
         " WHERE id = %s", hash_password(b.new_password), call.user["id"])
    tx.event("PASSWORD_CHANGED", "users", str(call.user["id"]), call.user["email"])
    # Sign out other sessions of this user.
    tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'password_changed'"
         " WHERE user_id = %s AND revoked_at IS NULL AND id <> %s", call.user["id"], call.user["session_id"])
    call.user["must_change_password"] = False
    return me_payload(call)


class PreferencesBody(BaseModel):
    language: Literal["en", "ar"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    checklist_hidden: bool | None = None
    tour_seen: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_-]+$")
    tours_reset: bool | None = None


@endpoint(auth="user", body=PreferencesBody, allow_password_change=True)
def preferences(call: Call):
    b = call.body
    if b.language is not None:
        call.tx.x("UPDATE users SET language = %s WHERE id = %s", b.language, call.user["id"])
        call.user["language"] = b.language
    if b.theme is not None:
        call.tx.x("UPDATE users SET theme = %s WHERE id = %s", b.theme, call.user["id"])
        call.user["theme"] = b.theme
    if b.checklist_hidden is not None or b.tour_seen or b.tours_reset:
        guide = dict(call.user.get("guide") or {})
        if b.checklist_hidden is not None:
            guide["checklist_hidden"] = b.checklist_hidden
        tours = [] if b.tours_reset else list(guide.get("tours") or [])
        if b.tour_seen and b.tour_seen not in tours:
            tours.append(b.tour_seen)
        guide["tours"] = tours[:60]
        call.tx.x("UPDATE users SET guide = %s::jsonb WHERE id = %s", json.dumps(guide), call.user["id"])
        call.user["guide"] = guide
    return {"ok": True, "guide": call.user.get("guide") or {}}
