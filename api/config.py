from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-flash-1.5"
    uploads_dir: str = "/data/uploads"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


settings = Settings()
