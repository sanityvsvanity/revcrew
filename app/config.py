"""Application configuration via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mode
    DEMO_MODE: bool = True
    ENV: str = "dev"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://revcrew:revcrew@localhost:5541/revcrew"

    # AI
    ANTHROPIC_API_KEY: str = ""
    MODEL_MAIN: str = "claude-sonnet-4-6"
    MODEL_FAST: str = "claude-haiku-4-5-20251001"

    # Slack
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    SLACK_CHANNEL_ID: str = ""

    # HubSpot
    HUBSPOT_PRIVATE_APP_TOKEN: str = ""

    # Instantly
    INSTANTLY_API_KEY: str = ""
    INSTANTLY_WEBHOOK_SECRET: str = ""

    # Agno Viz tracing
    TRACING_ENABLED: bool = False
    AGNO_VIZ_SPANS_URL: str = ""
    AGNO_VIZ_INGEST_TOKEN: str = ""

    # ICP
    ICP_SCORE_THRESHOLD: int = 70

    @property
    def icp_yaml_path(self) -> Path:
        return Path(__file__).parent / "icp.yaml"


settings = Settings()