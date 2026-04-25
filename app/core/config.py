from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PEXELS_API_KEY: str = ""
    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""
    YOUTUBE_REFRESH_TOKEN: str = ""
    INTERNAL_API_KEY: str = ""
    CHANNEL_NAME: str = "MyChannel"
    DB_PATH: str = "app/db/shorts.db"
    MEDIA_CACHE_DIR: str = "/tmp/pexels_cache"
    OUTPUT_DIR: str = "/tmp/shorts_output"
    SCHEDULER_ENABLED: bool = True
    SCHEDULE_TIMES: str = "00:10,06:10,12:10,18:10"
    SCHEDULE_TIMEZONE: str = "Asia/Kolkata"
    SCHEDULE_UPLOAD: bool = True
    SCHEDULE_NICHES: str = "horror,mystery"
    SCHEDULE_MISFIRE_GRACE_SECONDS: int = Field(default=3600, ge=60, le=86400)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    APP_URL: str = ""


settings = Settings()
