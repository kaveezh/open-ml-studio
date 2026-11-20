"""Environment configuration for Open ML Studio.

This module only reads configuration. It does not connect to Supabase or create
cloud resources during import. Cloud services are activated in later stages
after credentials and authentication are configured.
"""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_environment: str = Field(default="development", alias="APP_ENVIRONMENT")
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    app_password: SecretStr | None = Field(default=None, alias="APP_PASSWORD")

    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_anon_key: SecretStr | None = Field(default=None, alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: SecretStr | None = Field(default=None, alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_db_url: SecretStr | None = Field(default=None, alias="SUPABASE_DB_URL")
    supabase_storage_bucket: str = Field(default="open-ml-artifacts", alias="SUPABASE_STORAGE_BUCKET")

    max_upload_mb: int = Field(default=100, ge=1, le=500, alias="MAX_UPLOAD_MB")
    max_dataset_rows: int = Field(default=500_000, ge=2, le=5_000_000, alias="MAX_DATASET_ROWS")

    @model_validator(mode="after")
    def validate_storage_configuration(self) -> "Settings":
        if self.storage_backend not in {"local", "supabase"}:
            raise ValueError("STORAGE_BACKEND must be either 'local' or 'supabase'.")
        if self.storage_backend == "supabase":
            missing = [
                name for name, value in (
                    ("SUPABASE_URL", self.supabase_url),
                    ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
                    ("SUPABASE_DB_URL", self.supabase_db_url),
                ) if not value
            ]
            if missing:
                raise ValueError(
                    "Supabase storage is selected but required server settings are missing: "
                    + ", ".join(missing)
                )
        return self

    @property
    def supabase_configured(self) -> bool:
        return bool(
            self.supabase_url
            and self.supabase_service_role_key
            and self.supabase_db_url
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings; clear cache in tests after changing environment."""
    return Settings()
