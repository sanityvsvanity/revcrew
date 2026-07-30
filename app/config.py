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

    # Model provider (S7.1): auto|anthropic|ollama
    MODEL_PROVIDER: str = "auto"
    OLLAMA_HOST: str = ""  # e.g. http://localhost:11434
    OLLAMA_API_KEY: str = ""  # set with no host → defaults to ollama.cloud
    OLLAMA_MODEL_MAIN: str = "qwen3:14b"  # heavy roles
    OLLAMA_MODEL_FAST: str = "qwen3:4b"   # light roles

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

    # Guarded writes
    MAX_DEAL_AMOUNT: int = 10_000_000
    MAX_WRITES_PER_CONTEXT: int = 20
    DEAL_DEDUP: bool = True
    DEAL_PIPELINE_ID: str = "default"
    HUBSPOT_ALLOW_PROD: bool = False
    HUBSPOT_DEFAULT_OWNER_ID: str = ""
    RETENTION_DAYS: int = 90

    # ICP
    ICP_SCORE_THRESHOLD: int = 70
    ICP_PATH: str = ""  # empty = app/icp.yaml

    # Approval experience
    APPROVAL_REMINDER_HOURS: int = 24
    APPROVAL_TTL_HOURS: int = 72
    APPROVER_SLACK_IDS: str = ""  # comma-separated, empty = anyone in channel
    DEAL_DEFAULT_AMOUNT: str = ""
    DEAL_STAGE_DEFAULT: str = "prospecting"

    # Digest
    DIGEST_HOUR: int = 8
    DIGEST_TZ: str = "America/Chicago"

    # AgentOS auth
    OS_SECURITY_KEY: str = ""

    @property
    def icp_yaml_path(self) -> Path:
        if self.ICP_PATH:
            return Path(self.ICP_PATH)
        return Path(__file__).parent / "icp.yaml"

    @property
    def approver_ids(self) -> set[str]:
        if not self.APPROVER_SLACK_IDS.strip():
            return set()
        return {uid.strip() for uid in self.APPROVER_SLACK_IDS.split(",") if uid.strip()}


settings = Settings()