"""Comproof web application: JSON API under /api and the web app for everything else."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import settings
from .routers import audit_trail, auth, company, comparisons, library, platform

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("comproof")

API_ROUTES = [
    Route("/api/health", lambda r: JSONResponse({"status": "ok", "storage": "persistent" if settings.storage_persistent else "ephemeral"}), methods=["GET"]),
    # Authentication and personal settings
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/auth/me", auth.me, methods=["GET"]),
    Route("/api/auth/change-password", auth.change_password, methods=["POST"]),
    Route("/api/auth/preferences", auth.preferences, methods=["PATCH"]),
    # Platform administration
    Route("/api/platform/tenants", platform.list_tenants, methods=["GET"]),
    Route("/api/platform/tenants", platform.create_tenant, methods=["POST"]),
    Route("/api/platform/tenants/{tenant_id}", platform.update_tenant, methods=["PATCH"]),
    Route("/api/platform/tenants/{tenant_id}/admins", platform.list_tenant_admins, methods=["GET"]),
    Route("/api/platform/tenants/{tenant_id}/admins", platform.create_tenant_admin, methods=["POST"]),
    Route("/api/platform/users/{user_id}/reset-password", platform.reset_tenant_admin_password, methods=["POST"]),
    # Company administration
    Route("/api/sites", company.list_sites, methods=["GET"]),
    Route("/api/sites", company.create_site, methods=["POST"]),
    Route("/api/sites/{site_id}", company.update_site, methods=["PATCH"]),
    Route("/api/users", company.list_users, methods=["GET"]),
    Route("/api/users", company.create_user, methods=["POST"]),
    Route("/api/users/{user_id}", company.update_user, methods=["PATCH"]),
    Route("/api/users/{user_id}/roles", company.set_user_roles, methods=["PUT"]),
    Route("/api/users/{user_id}/reset-password", company.reset_user_password, methods=["POST"]),
    Route("/api/users/{user_id}/unlock", company.unlock_user, methods=["POST"]),
    Route("/api/settings", company.get_settings, methods=["GET"]),
    Route("/api/settings/company", company.update_company, methods=["PATCH"]),
    Route("/api/settings/features", company.update_features, methods=["PUT"]),
    Route("/api/settings/terminology", company.update_terminology, methods=["PUT"]),
    Route("/api/settings/security", company.update_security, methods=["PUT"]),
    Route("/api/settings/engine", company.update_engine, methods=["PUT"]),
    Route("/api/settings/engine/test", company.test_ai, methods=["POST"]),
    # Artwork library
    Route("/api/files", library.upload_file, methods=["POST"]),
    Route("/api/files/{file_id}/content", library.file_content, methods=["GET"]),
    Route("/api/products", library.list_products, methods=["GET"]),
    Route("/api/products", library.create_product, methods=["POST"]),
    Route("/api/products/{product_id}", library.get_product, methods=["GET"]),
    Route("/api/products/{product_id}", library.update_product, methods=["PATCH"]),
    Route("/api/products/{product_id}/components", library.create_component, methods=["POST"]),
    Route("/api/components", library.list_components, methods=["GET"]),
    Route("/api/components/{component_id}", library.get_component, methods=["GET"]),
    Route("/api/components/{component_id}", library.update_component, methods=["PATCH"]),
    Route("/api/components/{component_id}/artwork", library.create_artwork, methods=["POST"]),
    Route("/api/artwork/{artwork_id}/sign", library.sign_artwork, methods=["POST"]),
    Route("/api/components/{component_id}/shades", library.create_shade_set, methods=["POST"]),
    Route("/api/shades/{shade_id}/sign", library.sign_shade_set, methods=["POST"]),
    Route("/api/shades/{shade_id}/preview/{which}.jpg", library.shade_preview, methods=["GET"]),
    # Comparisons
    Route("/api/comparisons", comparisons.list_comparisons, methods=["GET"]),
    Route("/api/comparisons", comparisons.create_comparison, methods=["POST"]),
    Route("/api/comparisons/{comparison_id}", comparisons.get_comparison, methods=["GET"]),
    Route("/api/comparisons/{comparison_id}/status", comparisons.comparison_status, methods=["GET"]),
    Route("/api/comparisons/{comparison_id}/images/{name}", comparisons.comparison_image, methods=["GET"]),
    Route("/api/comparisons/{comparison_id}/decisions", comparisons.decide, methods=["POST"]),
    Route("/api/comparisons/{comparison_id}/sign", comparisons.sign_comparison, methods=["POST"]),
    Route("/api/comparisons/{comparison_id}/cancel", comparisons.cancel_comparison, methods=["POST"]),
    Route("/api/comparisons/{comparison_id}/retry", comparisons.retry_comparison, methods=["POST"]),
    Route("/api/comparisons/{comparison_id}/export.{fmt}", comparisons.export_comparison, methods=["GET"]),
    # Audit trail
    Route("/api/audit", audit_trail.list_audit, methods=["GET"]),
    Route("/api/audit/facets", audit_trail.audit_facets, methods=["GET"]),
    Route("/api/audit/export", audit_trail.export_audit, methods=["GET"]),
    Route("/api/audit/verify", audit_trail.verify_audit, methods=["POST"]),
]


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Content-Security-Policy",
                     "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;"
                     " font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self' blob:;"
                     " frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _frontend_routes() -> list:
    dist = Path(settings.frontend_dist).resolve()
    index = dist / "index.html"
    if not index.exists():
        log.warning("Web app build not found at %s; serving the API only.", dist)
        return [Route("/{path:path}", lambda r: PlainTextResponse(
            "The web app has not been built. Run the frontend build.", status_code=503))]

    async def spa(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Unknown API endpoint."}}, status_code=404)
        candidate = (dist / request.path_params.get("path", "")).resolve()
        if candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    routes = []
    if (dist / "assets").exists():
        routes.append(Mount("/assets", StaticFiles(directory=dist / "assets"), name="assets"))
    routes.append(Route("/{path:path}", spa))
    return routes


@asynccontextmanager
async def lifespan(app):
    if settings.run_migrations:
        from .migrate import bootstrap_platform_admin, migrate
        applied = migrate()
        if applied:
            log.info("Applied migrations: %s", ", ".join(applied))
        bootstrap_platform_admin()
    log.info("File store: %s (%s)", settings.data_dir, "persistent" if settings.storage_persistent else "NOT persistent")
    if not settings.storage_persistent:
        log.warning("No Railway volume is attached: uploads are refused until one is mounted.")
    from .worker import start
    start()
    yield


def create_app(run_lifespan: bool = True) -> Starlette:
    return Starlette(routes=API_ROUTES + _frontend_routes(),
                     middleware=[Middleware(SecurityHeaders)],
                     lifespan=lifespan if run_lifespan else None)


app = create_app()
