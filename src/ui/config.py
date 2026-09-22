from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardSettings(BaseSettings):
    GATEWAY_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = DashboardSettings()
