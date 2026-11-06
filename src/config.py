"""
Application settings loaded from environment variables (or a .env file).

Required variables:
  PORTAL_EMAIL     e-mail used to log in to the Urja portal
  PORTAL_PASSWORD  password for the above account

Optional variables:
  PORTAL_URL       base URL of the portal (default: https://urja-ops.flockenergy.tech)
  PORT             port on which this gateway will listen (default: 8000)
  LOG_LEVEL        Python log level name (default: INFO)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import HttpUrl


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    portal_url: HttpUrl = "https://urja-ops.flockenergy.tech"  # type: ignore[assignment]
    portal_email: str = "operator@urja.local"
    portal_password: str = "urja-ops-2026"

    port: int = 8000
    log_level: str = "INFO"


settings = Settings()

