"""Password hashing, password policy and session tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import string

# scrypt parameters (OWASP-recommended range). Stored with each hash so they can be raised later.
_N, _R, _P = 2 ** 15, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                                maxmem=_MAXMEM, dklen=len(expected))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# A valid hash of a random password, used to keep timing equal for unknown emails.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


DEFAULT_POLICY: dict = {
    "min_length": 10,
    "require_upper": True,
    "require_lower": True,
    "require_digit": True,
    "require_symbol": True,
    "expiry_days": 90,          # 0 = never expires
    "history": 5,               # previous passwords that cannot be reused
    "max_failed_attempts": 5,
    "lockout_minutes": 30,
    "session_timeout_minutes": 30,
}

POLICY_LIMITS: dict[str, tuple[int, int]] = {
    "min_length": (8, 64),
    "expiry_days": (0, 365),
    "history": (0, 24),
    "max_failed_attempts": (3, 10),
    "lockout_minutes": (5, 1440),
    "session_timeout_minutes": (5, 240),
}


def effective_policy(stored: dict | None) -> dict:
    policy = dict(DEFAULT_POLICY)
    for key, value in (stored or {}).items():
        if key in policy and type(value) is type(policy[key]):
            policy[key] = value
    return policy


def password_problems(password: str, policy: dict) -> list[str]:
    """Return policy rule codes the password breaks (empty list = acceptable)."""
    problems = []
    if len(password) < policy["min_length"]:
        problems.append("min_length")
    if policy["require_upper"] and not re.search(r"[A-Z]", password):
        problems.append("require_upper")
    if policy["require_lower"] and not re.search(r"[a-z]", password):
        problems.append("require_lower")
    if policy["require_digit"] and not re.search(r"\d", password):
        problems.append("require_digit")
    if policy["require_symbol"] and not re.search(r"[^A-Za-z0-9]", password):
        problems.append("require_symbol")
    if len(password) > 128:
        problems.append("max_length")
    return problems


def temporary_password(policy: dict) -> str:
    """Generate a one-time password that satisfies the policy."""
    length = max(14, policy["min_length"])
    symbols = "!@#$%*-_+=?"
    alphabet = string.ascii_letters + string.digits + symbols
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if not password_problems(pw, policy) and not re.search(r"[O0Il1]", pw):
            return pw


def new_session_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
