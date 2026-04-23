from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PEXELS_API_KEY: str = ""
    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""
    YOUTUBE_REFRESH_TOKEN: str = ""
    CHANNEL_NAME: str = "MyChannel"
    DB_PATH: str = "app/db/shorts.db"
    MEDIA_CACHE_DIR: str = "/tmp/pexels_cache"
    OUTPUT_DIR: str = "/tmp/shorts_output"
    SCHEDULE_HOUR: int = 9
    SCHEDULE_MINUTE: int = 0


settings = Settings()
