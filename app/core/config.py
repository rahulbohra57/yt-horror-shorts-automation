from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    SCHEDULE_HOUR: int = Field(default=9, ge=0, le=23)
    SCHEDULE_MINUTE: int = Field(default=0, ge=0, le=59)


settings = Settings()
