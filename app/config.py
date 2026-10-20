from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MacroPal API"
    environment: str = "production"

    database_url: str

    cors_origins: str = "*"

    default_page_size: int = 25
    max_page_size: int = 100

    fuzzy_threshold: float = 0.3

    firebase_credentials_file: str | None = None
    firebase_check_revoked: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
