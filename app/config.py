from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_id: int = Field(..., alias="TELEGRAM_OWNER_ID")
    telegram_channel_id: str = Field(..., alias="TELEGRAM_CHANNEL_ID")

    ozon_client_id: str = Field(..., alias="OZON_CLIENT_ID")
    ozon_api_key: str = Field(..., alias="OZON_API_KEY")
    ozon_base_url: str = Field("https://api-seller.ozon.ru", alias="OZON_BASE_URL")

    ollama_base_url: str = Field("http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("qwen2.5:7b", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: int = Field(300, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_num_predict: int = Field(650, alias="OLLAMA_NUM_PREDICT")

    database_url: str = Field("sqlite:///data/bot.sqlite3", alias="DATABASE_URL")
    app_mode: Literal["manual", "auto"] = Field("manual", alias="APP_MODE")
    post_style: Literal["info", "selling", "premium", "short", "long"] = Field("premium", alias="POST_STYLE")
    post_interval_minutes: int = Field(360, alias="POST_INTERVAL_MINUTES")
    max_products_per_sync: int = Field(20, alias="MAX_PRODUCTS_PER_SYNC")
    max_photos_per_post: int = Field(1, alias="MAX_PHOTOS_PER_POST")
    dry_run: bool = Field(False, alias="DRY_RUN")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    web_admin_username: str = Field("admin", alias="WEB_ADMIN_USERNAME")
    web_admin_password: str = Field("change_me", alias="WEB_ADMIN_PASSWORD")
    web_host: str = Field("0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(8080, alias="WEB_PORT")
    ozon_visibility: str = Field("VISIBLE", alias="OZON_VISIBILITY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
