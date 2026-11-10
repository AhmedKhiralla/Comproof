"""Background engine: runs queued comparisons, one at a time per worker thread.

The queue lives in the database, so nothing is lost when the server restarts: work that was
running is put back in the queue at start-up and runs again from the beginning.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import traceback

from . import db, storage
from .config import settings

log = logging.getLogger("comproof.worker")
_event = threading.Event()
_threads: list[threading.Thread] = []
ENGINE_USER = "Comproof engine"


def wake() -> None:
    _event.set()


def _ctx(tenant_id: str) -> db.Context:
    return db.Context(tenant_id=str(tenant_id), user_id=None, user_name=ENGINE_USER)


def _claim() -> dict | None:
    with db.pool().connection() as conn:
        tx = db.Tx(conn, db.SYSTEM)
        row = tx.one("SELECT * FROM cp_claim_comparison()")
        if not row:
            conn.commit()
            return None
        tx.apply(_ctx(row["tenant_id"]))
        c = tx.one(
            "SELECT c.*, rf.storage_key AS ref_key, rf.sha256 AS ref_sha, tf.storage_key AS test_key, tf.sha256 AS test_sha"
            "  FROM comparisons c JOIN files rf ON rf.id = c.reference_file_id LEFT JOIN files tf ON tf.id = c.test_file_id"
            " WHERE c.id = %s", row["id"])
        tx.x("UPDATE comparisons SET status = 'running', started_at = now(), progress = 'Starting', result_sha256 = NULL,"
             " result_summary = NULL WHERE id = %s", c["id"])
        tx.event("RUN_STARTED", "comparisons", str(c["id"]), c["number"], {"settings": c["settings"]})
        conn.commit()
        return c


def _progress(c: dict, msg: str) -> None:
    try:
        with db.transaction(_ctx(c["tenant_id"])) as tx:
            tx.x("UPDATE comparisons SET progress = %s WHERE id = %s AND status = 'running'", msg[:300], c["id"])
    except Exception:  # progress is best-effort
        log.debug("progress update failed", exc_info=True)


def _summary(res: dict) -> dict:
    out = {"steps": {}, "total": 0}
    for f in res["findings"]:
        s = out["steps"].setdefault(str(f["step"]), {"critical": 0, "major": 0, "minor": 0, "info": 0})
        s[f["severity"]] = s.get(f["severity"], 0) + 1
        if f["severity"] != "info":
            out["total"] += 1
    out["seconds"] = res.get("seconds")
    out["pages"] = {"approved": res["approved"]["pages"], "test": (res.get("design") or {}).get("pages", 0)}
    return out


def _load_shades(tenant: str, cfg: dict) -> dict:
    """The approved shade set, checked against the SHA-256 that was signed and recorded with the comparison."""
    from .routers.library import measurement_sha
    with db.transaction(_ctx(tenant)) as tx:
        s = tx.one("SELECT s.measurement, s.measurement_sha256, s.source, f.storage_key, f.sha256 FROM shade_sets s"
                   " JOIN files f ON f.id = s.standard_file_id WHERE s.id = %s::uuid", cfg["shade_set_id"])
    if not s:
        raise RuntimeError("The shade set of this comparison was not found.")
    if s["measurement_sha256"] != cfg["measurement_sha256"] or measurement_sha(s["measurement"]) != s["measurement_sha256"]:
        raise RuntimeError("The shade set measurement no longer matches its signed SHA-256.")
    std_path = storage.verify(s["storage_key"], s["sha256"]) if s["source"] != "spectro" else None
    return {"measurement": s["measurement"], "std_path": std_path}


def run_one(c: dict) -> None:
    from .engine import pipeline
    tenant = str(c["tenant_id"])
    out_dir = storage.work_dir(tenant, c["id"])
    storage.clear_work_dir(tenant, c["id"])
    try:
        ref = storage.verify(c["ref_key"], c["ref_sha"])
        test = storage.verify(c["test_key"], c["test_sha"]) if c["test_key"] else None
        run_settings = dict(c["settings"])
        colour_cfg = (run_settings.get("checks") or {}).get("colour")
        if colour_cfg:
            run_settings["_colour"] = _load_shades(tenant, colour_cfg)
        res = pipeline.run(ref, test, out_dir, run_settings, progress=lambda m: _progress(c, m))
        with open(os.path.join(out_dir, "result.json"), "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        summary = _summary(res)
        with db.transaction(_ctx(tenant)) as tx:
            tx.x("UPDATE comparisons SET status = 'review', finished_at = now(), progress = 'Ready for review',"
                 " engine_version = %s, ai_models = %s::jsonb, result_sha256 = %s, result_summary = %s::jsonb"
                 " WHERE id = %s", res["engine_version"], json.dumps(res.get("ai")), sha, json.dumps(summary), c["id"])
            tx.event("RUN_FINISHED", "comparisons", str(c["id"]), c["number"],
                     {"result_sha256": sha, "findings": summary["total"], "seconds": res.get("seconds")})
    except Exception as e:  # noqa: BLE001
        log.error("Comparison %s failed: %s", c["number"], traceback.format_exc())
        msg = str(e) or e.__class__.__name__
        with db.transaction(_ctx(tenant)) as tx:
            tx.x("UPDATE comparisons SET status = 'failed', finished_at = now(), progress = %s, error = %s WHERE id = %s",
                 ("Failed: " + msg)[:300], traceback.format_exc()[-4000:], c["id"])
            tx.event("RUN_FAILED", "comparisons", str(c["id"]), c["number"], {"error": msg[:500]})


def _loop() -> None:
    while True:
        try:
            c = _claim()
        except Exception:
            log.exception("Could not read the comparison queue")
            c = None
            time.sleep(5)
        if c:
            run_one(c)
            continue
        _event.wait(timeout=5)
        _event.clear()


def start() -> None:
    if _threads or not settings.run_worker:
        return
    try:
        with db.transaction(db.SYSTEM) as tx:
            n = tx.val("SELECT cp_requeue_interrupted()")
            if n:
                log.warning("Put %s interrupted comparisons back in the queue", n)
    except Exception:
        log.exception("Could not requeue interrupted comparisons")
    for i in range(max(1, settings.workers)):
        t = threading.Thread(target=_loop, name=f"comproof-engine-{i}", daemon=True)
        t.start()
        _threads.append(t)
