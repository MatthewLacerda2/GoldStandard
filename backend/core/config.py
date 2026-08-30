"""Application settings loaded from the environment and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application configuration.

    Values come from environment variables first, then a local `.env` file.
    Unknown keys are ignored so the same `.env` can serve multiple services.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"

    # RFC 7518 section 3.2 requires an HMAC key at least as long as the hash
    # output, so 32 bytes for SHA256. PyJWT only warns below that; we refuse to
    # start instead, so a weak signing key cannot reach production unnoticed.
    # 32 characters is always at least 32 bytes once UTF-8 encoded.
    JWT_SECRET: str = Field(default="change-me-in-production-min-32-bytes", min_length=32)
    JWT_ISSUER: str = "goldstandard"
    JWT_AUDIENCE: str = "goldstandard-app"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
    DEFAULT_ADMIN_PASSWORD: str = "change-me"

    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance."""
    return Settings()
