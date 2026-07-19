from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    database_url: str = "sqlite:///pos.db"
    public_url: str = "http://localhost:8080"


settings = Settings()
