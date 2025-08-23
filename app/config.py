import sys
from functools import lru_cache
from pathlib import Path

from loguru import logger as log
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    __version__: str = "0.0.1"

    # Network settings
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # Model and paths
    model_name: str = "gpt-5-mini"
    system_prompt_path: Path = Path("prompts/main_guide.md")
    conversations_dir: Path = Path("conversations")

    # Other settings
    max_history_messages: int | None = None

    # Environment variables
    openai_api_key: str = ""
    yandex_geocoder_api_key: str = ""
    ors_api_key: str = ""

    # Logging
    log_lvl: str = "INFO"
    log_path: Path = Path("logs/app.log")

    # External services
    yandex_geocoder_url: str = "https://geocode-maps.yandex.ru/v1"
    ors_directions_url: str = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
    rev_geocoder_concurrency: int = 4

    # pydantic-settings configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache()
def get_logger(log_path: Path, level: str):
    log.remove(0)
    log.add(sys.stderr, format="{time} | {level} | {message}", level=level)
    # Ensure log directory exists
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    log.add(
        log_path,
        format="{time} | {level} | {message}",
        level="DEBUG",
        rotation="1 days",
        retention="30 days",
        catch=True,
    )
    return log


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
logger = get_logger(settings.log_path, settings.log_lvl)

