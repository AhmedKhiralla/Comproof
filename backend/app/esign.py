"""Electronic signatures (21 CFR Part 11 §11.50, §11.70, §11.100, §11.200, §11.300).

* Each signing re-enters both components: the user's email (identification) and password.
* The signature stores the signer's printed name, the date and time (UTC, server clock), the meaning,
  and the SHA-256 of exactly what was signed, so it is linked to its record and cannot be moved to another.
* A wrong email or password is recorded in the audit trail and counts toward the account lockout,
  like a failed sign-in; reaching the limit locks the account and ends its sessions.
"""
from __future__ import annotations

from .api import ApiError, Call
from .security import verify_password

STATEMENTS = {
    "reviewed": "I have reviewed every finding of this comparison and my decisions are recorded accurately.",
    "approved": "I approve this comparison: the new packaging text conforms to the approved text, "
                "with any remaining differences assessed and accepted.",
    "rejected": "I reject this comparison: the new packaging text does not conform to the approved text "
                "and must be corrected.",
    "approved_master": "I approve this artwork version as the effective master for comparisons.",
    "withdrawn": "I withdraw this artwork version; it may no longer be used as a master.",
}


def sign(call: Call, *, entity: str, record_id: str, label: str, meaning: str, record_hash: str,
         email: str, password: str, reason: str | None = None) -> dict:
    tx, u = call.tx, call.user
    row = tx.one("SELECT email, password_hash, failed_attempts FROM users WHERE id = %s", u["id"])
    ok = email.strip().lower() == row["email"].lower() and verify_password(password, row["password_hash"])
    if not ok:
        policy = call.policy
        attempts = row["failed_attempts"] + 1
        locked = attempts >= policy["max_failed_attempts"]
        tx.event("SIGNATURE_FAILED", entity, record_id, label, {"meaning": meaning, "attempt": attempts, "locked": locked})
        if locked:
            tx.x("UPDATE users SET failed_attempts = 0, locked_until = now() + make_interval(mins => %s) WHERE id = %s",
                 policy["lockout_minutes"], u["id"])
            tx.x("UPDATE sessions SET revoked_at = now(), revoke_reason = 'signature_lockout'"
                 " WHERE user_id = %s AND revoked_at IS NULL", u["id"])
            tx.event("LOCKED", "users", str(u["id"]), u["email"], {"reason": "failed signatures"})
        else:
            tx.x("UPDATE users SET failed_attempts = %s WHERE id = %s", attempts, u["id"])
        tx.commit()  # keep the audit entry even though nothing is signed
        if locked:
            raise ApiError(401, "locked", "Too many failed signatures. Your account is locked; ask your administrator.")
        raise ApiError(403, "bad_signature", "The email or password is not correct. Nothing was signed.")
    tx.x("UPDATE users SET failed_attempts = 0 WHERE id = %s", u["id"])
    sig = tx.one(
        "INSERT INTO signatures (tenant_id, entity, record_id, record_label, meaning, statement, reason, record_hash,"
        " user_id, user_name, user_email) VALUES (%s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING id, meaning, statement, reason, user_name, user_email, signed_at, record_hash",
        call.tenant_id, entity, record_id, label, meaning, STATEMENTS[meaning], (reason or "").strip() or None,
        record_hash, u["id"], u["full_name"], row["email"])
    tx.event("SIGNED", entity, record_id, label, {"meaning": meaning, "record_hash": record_hash})
    return sig


def list_for(call: Call, entity: str, record_id: str) -> list[dict]:
    return call.tx.q("SELECT id, meaning, statement, reason, user_id, user_name, user_email, signed_at, record_hash"
                     " FROM signatures WHERE entity = %s AND record_id = %s::uuid ORDER BY id", entity, record_id)
