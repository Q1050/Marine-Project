"""Environment contract for development, test, demo, and pilot deployments."""
from dataclasses import dataclass
from pathlib import Path
import os


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    frontend_origins: tuple[str, ...]
    upload_directory: Path
    artifact_directory: Path
    backup_directory: Path
    log_level: str
    auth_secret: str | None
    event_worker_enabled: bool
    automatic_scientific_evaluation_enabled: bool
    provider_timeout_seconds: float
    max_upload_bytes: int
    rate_limit_login_per_minute: int
    rate_limit_submission_per_minute: int
    max_event_attempts: int
    backup_retention_count: int
    demo: bool
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 30

    @property
    def production_like(self) -> bool:
        return self.environment in {"PILOT", "PRODUCTION"}

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.environment not in {"DEVELOPMENT", "TEST", "DEMO", "PILOT", "PRODUCTION"}:
            errors.append("APP_ENV must be DEVELOPMENT, TEST, DEMO, PILOT, or PRODUCTION")
        if self.production_like and not self.auth_secret:
            errors.append("AUTH_SECRET is required for PILOT/PRODUCTION")
        if self.production_like and not self.frontend_origins:
            errors.append("CORS_ALLOWED_ORIGINS is required for PILOT/PRODUCTION")
        if self.production_like and any("localhost" in value or "127.0.0.1" in value for value in self.frontend_origins):
            errors.append("PILOT/PRODUCTION CORS origins must not use localhost")
        if self.automatic_scientific_evaluation_enabled and not self.event_worker_enabled:
            errors.append("Automatic scientific evaluation requires EVENT_WORKER_ENABLED")
        if self.demo and self.production_like:
            errors.append("DEMO_MODE cannot be enabled in PILOT/PRODUCTION")
        return errors


def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "DEVELOPMENT").upper()
    defaults = "http://localhost:5173,http://127.0.0.1:5173" if environment == "DEVELOPMENT" else ""
    return Settings(
        environment=environment,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./marine_observations.db"),
        frontend_origins=_csv("CORS_ALLOWED_ORIGINS", defaults),
        upload_directory=Path(os.getenv("UPLOAD_DIRECTORY", "uploads/observations")),
        artifact_directory=Path(os.getenv("ARTIFACT_DIRECTORY", "artifacts")),
        backup_directory=Path(os.getenv("BACKUP_DIRECTORY", "backups/managed")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        auth_secret=os.getenv("AUTH_SECRET"),
        event_worker_enabled=_bool("EVENT_WORKER_ENABLED"),
        automatic_scientific_evaluation_enabled=_bool("AUTOMATIC_SCIENTIFIC_EVALUATION_ENABLED"),
        provider_timeout_seconds=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "30")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        rate_limit_login_per_minute=int(os.getenv("RATE_LIMIT_LOGIN_PER_MINUTE", "10")),
        rate_limit_submission_per_minute=int(os.getenv("RATE_LIMIT_SUBMISSION_PER_MINUTE", "12")),
        max_event_attempts=int(os.getenv("MAX_EVENT_ATTEMPTS", "3")),
        backup_retention_count=int(os.getenv("BACKUP_RETENTION_COUNT", "14")),
        demo=environment == "DEMO" or _bool("DEMO_MODE"),
        database_pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
        database_max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "5")),
        database_pool_timeout_seconds=int(os.getenv("DATABASE_POOL_TIMEOUT_SECONDS", "30")),
    )


settings = load_settings()
