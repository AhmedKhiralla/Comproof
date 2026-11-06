"""Audit trail: filtered browsing and human-readable export (Excel / CSV)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from zoneinfo import ZoneInfo

from starlette.responses import Response

from ..api import ApiError, Call, endpoint

MAX_EXPORT_ROWS = 50_000


def _scope(call: Call) -> tuple[str, list]:
    """Extra WHERE clause on top of row-level security."""
    if call.user["is_platform_admin"]:
        # Platform admins see platform-level activity and company lifecycle events,
        # not the business activity inside companies.
        return ("(a.tenant_id IS NULL OR a.entity = 'tenants'"
                " OR a.user_id IN (SELECT id FROM users WHERE is_platform_admin))", [])
    return ("a.tenant_id = %s::uuid", [call.tenant_id])


def _filters(call: Call) -> tuple[str, list, dict]:
    clause, params = _scope(call)
    where, applied = [clause], {}
    q = call.query

    def add(sql: str, value, label: str):
        where.append(sql)
        params.append(value)
        applied[label] = value

    if q.get("entity"):
        add("a.entity = %s", q["entity"], "entity")
    if q.get("action"):
        add("a.action = %s", q["action"], "action")
    if q.get("user_id"):
        add("a.user_id = %s::uuid", q["user_id"], "user_id")
    if q.get("record_id"):
        add("a.record_id = %s", q["record_id"], "record_id")
    for key, op in (("from", ">="), ("to", "<")):
        raw = q.get(key)
        if raw:
            try:
                day = dt.date.fromisoformat(raw)
            except ValueError:
                raise ApiError(422, "invalid", "Some fields need attention.", fields={key: "Use YYYY-MM-DD."})
            if key == "to":
                day = day + dt.timedelta(days=1)
            add(f"a.occurred_at {op} (%s::date::timestamp AT TIME ZONE %s)", day.isoformat(), key)
            params.append(_tz(call))
    if q.get("q"):
        term = "%" + q["q"].replace("%", r"\%").replace("_", r"\_")[:100] + "%"
        where.append("(a.record_label ILIKE %s OR a.user_name ILIKE %s OR a.record_id ILIKE %s)")
        params += [term, term, term]
        applied["search"] = q["q"][:100]
    return " AND ".join(where), params, applied


def _tz(call: Call) -> str:
    if call.tenant_id:
        return call.tx.val("SELECT timezone FROM tenants WHERE id = %s", call.tenant_id) or "UTC"
    return "UTC"


COLUMNS = ("id, occurred_at, tenant_id, site_id, user_id, user_name, action, entity,"
           " record_id, record_label, old_values, new_values, details")


@endpoint(auth="user")
def list_audit(call: Call):
    if not (call.user["is_platform_admin"] or call.user["is_tenant_admin"]):
        raise ApiError(403, "forbidden", "Administrator access is required to view the audit trail.")
    where, params, _ = _filters(call)
    try:
        page = max(1, int(call.query.get("page", "1")))
        size = min(200, max(10, int(call.query.get("page_size", "50"))))
    except ValueError:
        raise ApiError(422, "invalid", "Page must be a number.")
    total = call.tx.val(f"SELECT count(*) FROM audit_log a WHERE {where}", *params)
    rows = call.tx.q(f"SELECT {COLUMNS} FROM audit_log a WHERE {where}"
                     " ORDER BY a.occurred_at DESC, a.id DESC LIMIT %s OFFSET %s",
                     *params, size, (page - 1) * size)
    return {"items": rows, "total": total, "page": page, "page_size": size}


@endpoint(auth="user")
def audit_facets(call: Call):
    if not (call.user["is_platform_admin"] or call.user["is_tenant_admin"]):
        raise ApiError(403, "forbidden", "Administrator access is required to view the audit trail.")
    clause, params = _scope(call)
    return {
        "entities": [r["entity"] for r in call.tx.q(
            f"SELECT DISTINCT a.entity FROM audit_log a WHERE {clause} ORDER BY 1", *params)],
        "actions": [r["action"] for r in call.tx.q(
            f"SELECT DISTINCT a.action FROM audit_log a WHERE {clause} ORDER BY 1", *params)],
        "users": call.tx.q(
            f"SELECT DISTINCT ON (a.user_id) a.user_id AS id, a.user_name AS name FROM audit_log a"
            f" WHERE {clause} AND a.user_id IS NOT NULL ORDER BY a.user_id, a.occurred_at DESC", *params),
    }


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


@endpoint(auth="user")
def export_audit(call: Call):
    if not (call.user["is_platform_admin"] or call.user["is_tenant_admin"]):
        raise ApiError(403, "forbidden", "Administrator access is required to export the audit trail.")
    fmt = call.query.get("format", "xlsx")
    if fmt not in ("xlsx", "csv"):
        raise ApiError(422, "invalid", "Format must be xlsx or csv.")
    where, params, applied = _filters(call)
    total = call.tx.val(f"SELECT count(*) FROM audit_log a WHERE {where}", *params)
    if total > MAX_EXPORT_ROWS:
        raise ApiError(422, "too_many_rows",
                       f"The export has {total} entries. Narrow the filters to {MAX_EXPORT_ROWS} or fewer.")
    rows = call.tx.q(f"SELECT {COLUMNS} FROM audit_log a WHERE {where} ORDER BY a.occurred_at, a.id", *params)

    tz_name = _tz(call)
    tz = ZoneInfo(tz_name)
    now_utc = call.tx.val("SELECT now()")
    exported_at = now_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") + f" ({tz_name})"
    company = call.tx.val("SELECT name FROM tenants WHERE id = %s", call.tenant_id) if call.tenant_id else "Platform"
    meta = [
        ("Report", "Audit trail"),
        ("Company", company),
        ("Exported by", f"{call.user['full_name']} <{call.user['email']}>"),
        ("Exported at", exported_at),
        ("Filters", ", ".join(f"{k}={v}" for k, v in applied.items()) or "none"),
        ("Entries", str(len(rows))),
    ]
    header = ["Entry", f"Time ({tz_name})", "User", "Action", "Entity", "Record", "Record ID",
              "Old values", "New values", "Details"]
    body = [[r["id"], r["occurred_at"].astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"), r["user_name"],
             r["action"], r["entity"], r["record_label"], r["record_id"],
             _fmt(r["old_values"]), _fmt(r["new_values"]), _fmt(r["details"])] for r in rows]

    call.tx.event("EXPORT", "audit_log", None, "Audit trail",
                  {"format": fmt, "filters": applied, "rows": len(rows)})

    stamp = now_utc.astimezone(tz).strftime("%Y%m%d-%H%M")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        for k, v in meta:
            w.writerow([k, v])
        w.writerow([])
        w.writerow(header)
        w.writerows(body)
        data = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads Arabic correctly
        media = "text/csv; charset=utf-8"
    else:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "Audit trail"
        for k, v in meta:
            ws.append([k, v])
            ws.cell(ws.max_row, 1).font = Font(bold=True)
        ws.append([])
        ws.append(header)
        head_row = ws.max_row
        for cell in ws[head_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="67138C")
        for row in body:
            ws.append(row)
        widths = [8, 20, 24, 16, 18, 28, 38, 60, 60, 40]
        for i, wdt in enumerate(widths, start=1):
            ws.column_dimensions[chr(64 + i)].width = wdt
        for row in ws.iter_rows(min_row=head_row + 1):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=cell.column >= 8)
        ws.freeze_panes = ws.cell(head_row + 1, 1)
        ws.oddFooter.left.text = f"Exported by {call.user['full_name']} at {exported_at}"
        ws.oddFooter.right.text = "Page &P of &N"
        out = io.BytesIO()
        wb.save(out)
        data = out.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="audit-trail-{stamp}.{fmt}"'})


@endpoint(auth="user")
def verify_audit(call: Call):
    """Recompute the tamper-evident hash chain of the caller's company (or of the platform)."""
    if not (call.user["is_platform_admin"] or call.user["is_tenant_admin"]):
        raise ApiError(403, "forbidden", "Administrator access is required.")
    row = call.tx.one("SELECT * FROM cp_audit_verify(%s::uuid)", call.tenant_id)
    ok = row["first_bad_id"] is None
    call.tx.event("INTEGRITY_CHECK", "audit_log", None, "audit trail",
                  {"checked": row["checked"], "intact": ok, "first_bad_id": row["first_bad_id"]})
    return {"checked": row["checked"], "intact": ok, "first_bad_id": row["first_bad_id"]}
