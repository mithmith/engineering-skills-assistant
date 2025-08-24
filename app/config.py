import sys
from functools import lru_cache
from pathlib import Path

from loguru import logger as log
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    __version__: str = "0.0.2"

    # Network settings
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # Model and paths
    model_name: str = "gpt-5"
    system_prompt_path: Path = Path("prompts/skills_assistant.md")
    conversations_dir: Path = Path("conversations")

    # History / context control
    max_history_messages: int | None = None  # legacy fallback
    summary_enabled: bool = True
    summary_keep_last_messages: int = 12  # сколько «живых» реплик держать помимо summary
    summary_update_every_n_turns: int = 6  # как часто пересвёртывать (по ходам ассистента)
    summary_max_chars: int = 4000  # грубый лимит размера summary
    summary_model_name: str | None = None  # по умолчанию = model_name

    # Environment variables
    openai_api_key: str = ""
    telegram_token: str = ""

    # Logging
    log_lvl: str = "INFO"
    log_path: Path = Path("logs/app.log")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache()
def get_logger(log_path: Path, level: str):
    log.remove(0)
    log.add(sys.stderr, format="{time} | {level} | {message}", level=level)
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
