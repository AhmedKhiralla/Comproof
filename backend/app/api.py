"""Thin request handling layer on top of Starlette.

``@endpoint`` wraps a handler with: CSRF header check, session authentication,
role checks, request body validation (pydantic), one database transaction with
the caller's security context, JSON serialisation and consistent error bodies.
"""
from __future__ import annotations

import datetime as dt
import decimal
import functools
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import psycopg
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import db
from .config import settings
from .security import effective_policy, token_hash

log = logging.getLogger("comproof")

SESSION_COOKIE = "cpf_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "comproof"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict | None = None,
                 extra: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.fields, self.extra = status, code, message, fields, extra


def not_found(what: str = "Record") -> ApiError:
    return ApiError(404, "not_found", f"{what} was not found.")


def _default(o: Any):
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, dt.datetime):
        if o.tzinfo is None:
            o = o.replace(tzinfo=dt.timezone.utc)
        return o.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(o, (dt.date, dt.time)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    raise TypeError(f"Cannot serialise {type(o).__name__}")


class JSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=_default, ensure_ascii=False, separators=(",", ":")).encode()


def error_response(err: ApiError) -> JSON:
    body: dict[str, Any] = {"error": {"code": err.code, "message": err.message}}
    if err.fields:
        body["error"]["fields"] = err.fields
    if err.extra:
        body["error"].update(err.extra)
    return JSON(body, status_code=err.status)


@dataclass
class Call:
    request: Request
    tx: db.Tx
    user: dict | None
    body: Any
    path: dict
    cookies_to_set: list[tuple[str, str, int]] = field(default_factory=list)
    cookies_to_clear: list[str] = field(default_factory=list)

    @property
    def query(self):
        return self.request.query_params

    @property
    def tenant_id(self) -> str | None:
        return str(self.user["tenant_id"]) if self.user and self.user["tenant_id"] else None

    @property
    def policy(self) -> dict:
        return effective_policy(self.user.get("tenant_security") if self.user else None)

    def client_ip(self) -> str | None:
        fwd = self.request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return self.request.client.host if self.request.client else None


def user_context(user: dict) -> db.Context:
    return db.Context(
        tenant_id=str(user["tenant_id"]) if user["tenant_id"] else None,
        user_id=str(user["id"]),
        user_name=user["full_name"],
        is_platform=bool(user["is_platform_admin"]),
    )


SESSION_SQL = """
SELECT s.id AS session_id, s.last_seen_at, s.expires_at, s.revoked_at,
       u.id, u.tenant_id, u.email, u.full_name, u.is_platform_admin, u.is_tenant_admin,
       u.status, u.language, u.theme, u.must_change_password, u.password_changed_at, u.guide,
       t.status AS tenant_status, t.security AS tenant_security, now() AS db_now
  FROM sessions s
  JOIN users u ON u.id = s.user_id
  LEFT JOIN tenants t ON t.id = u.tenant_id
 WHERE s.token_hash = %s
"""


def authenticate(call: Call) -> dict:
    token = call.request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "not_signed_in", "Sign in to continue.")
    tx = call.tx
    row = tx.one(SESSION_SQL, token_hash(token))
    if not row or row["revoked_at"] is not None:
        raise ApiError(401, "not_signed_in", "Sign in to continue.")
    now = row["db_now"]
    timeout = dt.timedelta(minutes=effective_policy(row["tenant_security"])["session_timeout_minutes"])
    expired_reason = None
    if now > row["expires_at"]:
        expired_reason = "max_lifetime"
    elif now - row["last_seen_at"] > timeout:
        expired_reason = "inactivity"
    if expired_reason:
        tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = %s WHERE id = %s",
             expired_reason, row["session_id"])
        tx.event("SESSION_TIMEOUT", "sessions", str(row["session_id"]), row["email"],
                 {"reason": expired_reason}, tenant_id=str(row["tenant_id"]) if row["tenant_id"] else None,
                 user_id=str(row["id"]), user_name=row["full_name"])
        tx.commit()
        tx.apply(db.SYSTEM)
        raise ApiError(401, "session_expired", "Your session ended after a period of inactivity. Sign in again.")
    if row["status"] != "active":
        raise ApiError(401, "not_signed_in", "This account is disabled.")
    if row["tenant_id"] and row["tenant_status"] != "active":
        raise ApiError(401, "not_signed_in", "This company account is suspended.")
    if now - row["last_seen_at"] > dt.timedelta(seconds=30):
        tx.x("UPDATE sessions SET last_seen_at = now() WHERE id = %s", row["session_id"])
    return row


def endpoint(auth: str | None = "user", body: type[BaseModel] | None = None,
             allow_password_change: bool = False, raw: bool = False):
    """auth: None | 'user' | 'tenant_user' | 'tenant_admin' | 'platform'."""

    def wrap(fn: Callable[[Call], Any]):
        @functools.wraps(fn)
        def handler(request: Request):
            return _handle(fn, request, auth, body, allow_password_change)
        handler.__comproof_raw__ = raw
        return handler

    return wrap


def _read_json(request: Request) -> Any:
    import anyio.from_thread
    raw = anyio.from_thread.run(request.body)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise ApiError(400, "invalid_json", "The request body is not valid JSON.")


def _handle(fn, request: Request, auth, body_model, allow_password_change):
    try:
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and \
                request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise ApiError(403, "csrf", "Request rejected: missing application header.")
        payload = None
        if body_model is not None:
            data = _read_json(request)
            try:
                payload = body_model.model_validate(data)
            except ValidationError as e:
                fields = {}
                for err in e.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or "_"
                    fields.setdefault(loc, err["msg"])
                raise ApiError(422, "invalid", "Some fields need attention.", fields=fields)

        with db.pool().connection() as conn:
            tx = db.Tx(conn, db.SYSTEM)
            call = Call(request=request, tx=tx, user=None, body=payload, path=dict(request.path_params))
            try:
                if auth is not None:
                    user = authenticate(call)
                    tx.apply(user_context(user))
                    call.user = user
                    if user["must_change_password"] and not allow_password_change:
                        raise ApiError(403, "password_change_required", "Change your password to continue.")
                    if auth == "platform" and not user["is_platform_admin"]:
                        raise ApiError(403, "forbidden", "Platform administrator access is required.")
                    if auth in ("tenant_user", "tenant_admin") and not user["tenant_id"]:
                        raise ApiError(403, "forbidden", "This action is available to company users only.")
                    if auth == "tenant_admin" and not user["is_tenant_admin"]:
                        raise ApiError(403, "forbidden", "Company administrator access is required.")
                else:
                    tx.apply(db.ANONYMOUS)
                result = fn(call)
                conn.commit()
            except ApiError as err:
                conn.rollback()
                # Keep audit events (e.g. failed sign-in) that the handler committed itself.
                return _finish(error_response(err), call)
            except psycopg.Error as err:
                conn.rollback()
                return _finish(error_response(_db_error(err)), call)
        response = result if isinstance(result, Response) else JSON(result if result is not None else {"ok": True})
        return _finish(response, call)
    except ApiError as err:
        return error_response(err)
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(ApiError(500, "server_error", "Something went wrong on the server. Try again; if it repeats, contact support."))


def _finish(response: Response, call: Call) -> Response:
    for name, value, max_age in call.cookies_to_set:
        response.set_cookie(name, value, max_age=max_age, httponly=True, secure=settings.cookie_secure,
                            samesite="strict", path="/")
    for name in call.cookies_to_clear:
        response.delete_cookie(name, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


def _db_error(err: psycopg.Error) -> ApiError:
    state = getattr(err, "sqlstate", None)
    if state == "23505":
        return ApiError(409, "duplicate", "A record with the same code or email already exists.")
    if state == "23514":
        return ApiError(422, "invalid", "A value is not in the allowed format.")
    if state == "23503":
        return ApiError(409, "in_use", "This record is linked to other data.")
    if state == "42501":
        return ApiError(403, "forbidden", "You do not have access to this record.")
    log.error("Database error %s: %s", state, err)
    return ApiError(500, "server_error", "Something went wrong on the server. Try again; if it repeats, contact support.")
