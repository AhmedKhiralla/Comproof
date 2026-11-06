"""Database access: a small connection pool and a per-request transaction.

Every application transaction runs as the restricted role ``comproof_app`` so that
row-level security is enforced by PostgreSQL itself. The request context
(tenant, user, platform flag) is applied at the start of each transaction.
"""
from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from .config import settings


@dataclass
class Context:
    """Who is acting. Applied to every transaction via set_config()."""
    tenant_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    is_platform: bool = False
    is_system: bool = False


SYSTEM = Context(is_system=True, user_name="system")
ANONYMOUS = Context()


class Pool:
    def __init__(self, dsn: str, size: int):
        self._dsn = dsn
        self._idle: "queue.LifoQueue[psycopg.Connection]" = queue.LifoQueue()
        self._sem = threading.BoundedSemaphore(size)

    def _new(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn, autocommit=False, row_factory=dict_row)
        conn.execute("SET TIME ZONE 'UTC'")
        conn.commit()
        return conn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        self._sem.acquire()
        conn = None
        try:
            try:
                conn = self._idle.get_nowait()
                if conn.closed:
                    conn = self._new()
            except queue.Empty:
                conn = self._new()
            yield conn
        except Exception:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    conn.close()
            raise
        finally:
            if conn is not None and not conn.closed:
                try:
                    conn.rollback()  # never leave a transaction open in the pool
                    self._idle.put(conn)
                except Exception:
                    conn.close()
            self._sem.release()


_pool: Pool | None = None
_pool_lock = threading.Lock()


def pool() -> Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = Pool(settings.database_url, settings.db_pool_size)
        return _pool


def reset_pool(dsn: str | None = None) -> None:
    """Used by tests to point the app at another database."""
    global _pool
    with _pool_lock:
        _pool = Pool(dsn or settings.database_url, settings.db_pool_size)


class Tx:
    """One database transaction with an applied security context."""

    def __init__(self, conn: psycopg.Connection, ctx: Context):
        self.conn = conn
        self.ctx = ctx
        self.apply(ctx)

    def apply(self, ctx: Context) -> None:
        self.ctx = ctx
        self.conn.execute("SET LOCAL ROLE comproof_app")
        self.conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
            " set_config('app.user_name', %s, true), set_config('app.is_platform', %s, true),"
            " set_config('app.is_system', %s, true)",
            (ctx.tenant_id or "", ctx.user_id or "", ctx.user_name or "",
             "true" if ctx.is_platform else "false", "true" if ctx.is_system else "false"),
        )

    def q(self, sql: str, *params: Any) -> list[dict]:
        return self.conn.execute(sql, params if params else None).fetchall()

    def one(self, sql: str, *params: Any) -> dict | None:
        return self.conn.execute(sql, params if params else None).fetchone()

    def val(self, sql: str, *params: Any) -> Any:
        row = self.one(sql, *params)
        return None if row is None else next(iter(row.values()))

    def x(self, sql: str, *params: Any) -> int:
        return self.conn.execute(sql, params if params else None).rowcount

    def event(self, action: str, entity: str, record_id: str | None = None,
              label: str | None = None, details: dict | None = None,
              tenant_id: str | None = None, user_id: str | None = None,
              user_name: str | None = None) -> None:
        """Write a non-row audit event (sign-in, export...)."""
        import json
        self.x(
            "SELECT cp_audit_event(%s, %s, %s, %s, %s::jsonb, %s::uuid, %s::uuid, %s)",
            action, entity, record_id, label,
            json.dumps(details) if details is not None else None,
            tenant_id if tenant_id is not None else self.ctx.tenant_id,
            user_id if user_id is not None else self.ctx.user_id,
            user_name if user_name is not None else self.ctx.user_name,
        )

    def commit(self) -> None:
        self.conn.commit()


@contextmanager
def transaction(ctx: Context = ANONYMOUS) -> Iterator[Tx]:
    with pool().connection() as conn:
        tx = Tx(conn, ctx)
        yield tx
        conn.commit()
