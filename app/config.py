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
    web_session_secret: str = Field("change_me_session_secret", alias="WEB_SESSION_SECRET")
    web_host: str = Field("0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(8080, alias="WEB_PORT")
    ozon_visibility: str = Field("VISIBLE", alias="OZON_VISIBILITY")
    image_engine: str = Field("none", alias="IMAGE_ENGINE")
    comfyui_base_url: str = Field("http://127.0.0.1:8188", alias="COMFYUI_BASE_URL")
    hf_token: str | None = Field(None, alias="HF_TOKEN")
    hf_image_model: str = Field("stabilityai/stable-diffusion-xl-refiner-1.0", alias="HF_IMAGE_MODEL")
    hf_image_provider: str = Field("auto", alias="HF_IMAGE_PROVIDER")
    hf_image_width: int = Field(1024, alias="HF_IMAGE_WIDTH")
    hf_image_height: int = Field(1280, alias="HF_IMAGE_HEIGHT")
    image_generation_mode: str = Field("image_to_image", alias="IMAGE_GENERATION_MODE")
    local_sdcpp_bin: str = Field("/opt/stable-diffusion.cpp/build/bin/sd-cli", alias="LOCAL_SDCPP_BIN")
    local_image_model: str = Field(
        "/opt/tgchannelSeb/models/sd15-gguf/stable-diffusion-v1-5-Q4_0.gguf",
        alias="LOCAL_IMAGE_MODEL",
    )
    local_image_width: int = Field(512, alias="LOCAL_IMAGE_WIDTH")
    local_image_height: int = Field(640, alias="LOCAL_IMAGE_HEIGHT")
    local_image_steps: int = Field(20, alias="LOCAL_IMAGE_STEPS")
    local_image_strength: float = Field(0.30, alias="LOCAL_IMAGE_STRENGTH")
    local_image_cfg_scale: float = Field(6.5, alias="LOCAL_IMAGE_CFG_SCALE")
    local_image_seed: int = Field(-1, alias="LOCAL_IMAGE_SEED")
    local_image_threads: int = Field(4, alias="LOCAL_IMAGE_THREADS")
    local_image_timeout_seconds: int = Field(1800, alias="LOCAL_IMAGE_TIMEOUT_SECONDS")
    freetheai_api_key: str | None = Field(None, alias="FREETHEAI_API_KEY")
    freetheai_base_url: str = Field("https://api.freetheai.xyz/v1", alias="FREETHEAI_BASE_URL")
    freetheai_image_model: str = Field("img/gpt-image-2", alias="FREETHEAI_IMAGE_MODEL")
    freetheai_timeout_seconds: int = Field(180, alias="FREETHEAI_TIMEOUT_SECONDS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
