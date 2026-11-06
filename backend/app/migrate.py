"""Applies SQL migrations in order and creates the first platform administrator."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .security import hash_password, password_problems, DEFAULT_POLICY

log = logging.getLogger("comproof")
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
LOCK_ID = 727_021  # advisory lock so two instances never migrate at once


def migrate(dsn: str | None = None) -> list[str]:
    applied_now: list[str] = []
    conn = psycopg.connect(dsn or settings.database_url, autocommit=False, row_factory=dict_row)
    try:
        encoding = conn.execute("SHOW server_encoding").fetchone()["server_encoding"]
        if encoding.upper() not in ("UTF8", "UTF-8"):
            raise RuntimeError(f"The database encoding is {encoding}; Comproof needs UTF8 for Arabic text.")
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        conn.commit()
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        conn.commit()
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            log.info("Applying migration %s", version)
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            conn.commit()
            applied_now.append(version)
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return applied_now


def bootstrap_platform_admin(dsn: str | None = None) -> str | None:
    """Create the first platform administrator from environment variables, once."""
    email = (settings.platform_admin_email or "").strip().lower()
    password = settings.platform_admin_password or ""
    if not email or not password:
        return None
    conn = psycopg.connect(dsn or settings.database_url, autocommit=False, row_factory=dict_row)
    try:
        exists = conn.execute("SELECT 1 FROM users WHERE is_platform_admin LIMIT 1").fetchone()
        if exists:
            conn.commit()
            return None
        problems = password_problems(password, DEFAULT_POLICY)
        if problems:
            raise RuntimeError("PLATFORM_ADMIN_PASSWORD does not meet the password policy: " + ", ".join(problems))
        conn.execute("SELECT set_config('app.user_name', 'system', true)")
        row = conn.execute(
            "INSERT INTO users (tenant_id, email, full_name, password_hash, is_platform_admin, must_change_password)"
            " VALUES (NULL, %s, %s, %s, true, true) RETURNING id",
            (email, settings.platform_admin_name, hash_password(password))).fetchone()
        conn.execute("SELECT cp_audit_event('BOOTSTRAP', 'users', %s, %s, NULL, NULL, NULL, 'system')",
                     (str(row["id"]), email))
        conn.commit()
        log.info("Created platform administrator %s", email)
        return email
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Applied:", migrate() or "nothing new")
    bootstrap_platform_admin()
