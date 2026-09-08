from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PACIFICEO_",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: SecretStr
    supabase_url: str = ""
    supabase_jwt_secret: SecretStr | None = None
    stac_api_url: str = "https://earth-search.aws.element84.com/v1"
    titiler_url: str = ""
    tile_signing_secret: SecretStr | None = None
    tile_allowed_hosts: str = ""
    tile_token_minutes: int = 5
    scheduler_poll_seconds: int = 60
    primary_grace_minutes: int = 30
    runner_lease_minutes: int = 120
    scheduler_enabled: bool = True
    runner_name: str = "primary"
    dashboard_origin: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
