"""Runtime configuration, read from environment variables."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/comproof")
    # Railway and Heroku style URLs work directly with libpq; normalise the scheme.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    # Cookies are marked Secure unless explicitly disabled for local development.
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    # Absolute session lifetime; the inactivity timeout comes from tenant security policy.
    session_max_hours: int = field(default_factory=lambda: int(os.environ.get("SESSION_MAX_HOURS", "12")))
    db_pool_size: int = field(default_factory=lambda: int(os.environ.get("DB_POOL_SIZE", "10")))
    platform_admin_email: str | None = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_EMAIL"))
    platform_admin_password: str | None = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_PASSWORD"))
    platform_admin_name: str = field(default_factory=lambda: os.environ.get("PLATFORM_ADMIN_NAME", "Platform administrator"))
    frontend_dist: str = field(default_factory=lambda: os.environ.get(
        "FRONTEND_DIST",
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")))
    run_migrations: bool = field(default_factory=lambda: _bool("RUN_MIGRATIONS", True))
    # Controlled file store: uploads, results and screenshots. Mount a persistent volume here.
    # On Railway the attached volume's mount path wins, so files always land on the persistent disk.
    data_dir: str = field(default_factory=lambda: os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
                          or os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")))
    # False only on Railway without a volume: uploads are refused rather than lost at the next deploy.
    storage_persistent: bool = field(default_factory=lambda: not (
        os.environ.get("RAILWAY_PROJECT_ID") or os.environ.get("RAILWAY_ENVIRONMENT_NAME"))
        or bool(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")) or _bool("ALLOW_EPHEMERAL_STORAGE", False))
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("MAX_UPLOAD_MB", "60")))
    # Comparisons run in background threads inside the web process.
    workers: int = field(default_factory=lambda: int(os.environ.get("ENGINE_WORKERS", "1")))
    run_worker: bool = field(default_factory=lambda: _bool("RUN_WORKER", True))


settings = Settings()
