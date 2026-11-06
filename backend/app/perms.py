"""Who may do what in Comproof.

Roles are given per site:
  artwork_editor  registers products, packaging components and approved artwork versions; starts comparisons
  reviewer        starts comparisons, records a decision on each finding, signs "Reviewed"
  approver        signs approvals: an approved master artwork, a comparison approved or rejected
  viewer          reads

Company-wide data (products, components, artwork library) is edited by company administrators and by
artwork editors of any site, and read by every company user. Comparisons belong to a site.

Electronic signatures are never implied by the administrator flag: an administrator who must sign
gives themselves the approver or reviewer role, so the audit trail shows the signing authority.
"""
from __future__ import annotations

from .api import ApiError, Call


def _roles(call: Call) -> list[dict]:
    cached = getattr(call, "_roles", None)
    if cached is None:
        cached = call.tx.q("SELECT site_id::text AS site_id, role FROM user_site_roles WHERE user_id = %s",
                           call.user["id"])
        setattr(call, "_roles", cached)
    return cached


def has_any(call: Call, role: str) -> bool:
    return any(r["role"] == role for r in _roles(call))


def site_roles(call: Call, site_id: str) -> set[str]:
    return {r["role"] for r in _roles(call) if r["site_id"] == str(site_id)}


def can_edit_library(call: Call) -> bool:
    return bool(call.user["is_tenant_admin"]) or has_any(call, "artwork_editor")


def require_library_edit(call: Call) -> None:
    if not can_edit_library(call):
        raise ApiError(403, "forbidden", "Artwork editor access is required to change the artwork library.")


def require_signer(call: Call, role: str, site_id: str | None = None) -> None:
    ok = role in site_roles(call, site_id) if site_id else has_any(call, role)
    if not ok:
        what = "approver" if role == "approver" else "reviewer"
        raise ApiError(403, "forbidden", f"Only users with the {what} role can sign this.")


def require_site(call: Call, site_id: str) -> dict:
    """Return the site after checking the caller may read it."""
    site = call.tx.one("SELECT id, code, name, country, timezone, active FROM sites WHERE id = %s::uuid", str(site_id))
    if not site:
        raise ApiError(404, "not_found", "Site was not found.")
    if call.user["is_tenant_admin"] or site_roles(call, site_id):
        return site
    raise ApiError(403, "forbidden", "You do not have access to this site.")


def can_start(call: Call, site_id: str) -> bool:
    return bool(call.user["is_tenant_admin"]) or bool(site_roles(call, site_id) & {"reviewer", "artwork_editor"})


def can_decide(call: Call, site_id: str) -> bool:
    return "reviewer" in site_roles(call, site_id)


def visible_site_ids(call: Call) -> list[str] | None:
    """None = all sites (administrators)."""
    if call.user["is_tenant_admin"]:
        return None
    return sorted({r["site_id"] for r in _roles(call)})
