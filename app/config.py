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

    # Research stack (docs/research-stack.md). Every key is optional; each
    # tier degrades to the next cheaper one and the ledger records which ran.
    RESEARCH_PROVIDER: str = "auto"  # scrape tier: auto | basic | firecrawl
    FIRECRAWL_API_KEY: str = ""
    SERPER_API_KEY: str = ""          # Tier 1 search (Google SERP); falls back to Firecrawl search, then DuckDuckGo
    SERPER_GL: str = "au"             # Google country code for Serper results
    JINA_API_KEY: str = ""            # optional; r.jina.ai works keyless at a lower rate limit
    BROWSERBASE_API_KEY: str = ""     # Tier 3 browser hands (Stagehand on Browserbase)
    BROWSERBASE_PROJECT_ID: str = ""
    RESEARCH_BROWSER_ENABLED: bool = False   # browser tier is opt-in
    STAGEHAND_MODEL: str = ""         # "provider/model"; empty = Browserbase Model Gateway
    STAGEHAND_MODEL_API_KEY: str = ""  # empty = ANTHROPIC_API_KEY when STAGEHAND_MODEL is anthropic/*
    RESEARCH_DENY_DOMAINS: str = ""   # comma-separated, added to the built-in deny list
    RESEARCH_CACHE_TTL_HOURS: int = 48
    RESEARCH_MAX_CALLS_PER_ACCOUNT: int = 25
    RESEARCH_MAX_CREDITS_PER_ACCOUNT: float = 40
    RESEARCH_MAX_BROWSER_SECONDS_PER_ACCOUNT: float = 180
    RESEARCH_MAX_USD_PER_ACCOUNT: float = 0.50
    RESEARCH_FETCH_MAX_CHARS: int = 6000
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

    # Tracing: TRACING_ENABLED writes agno's OpenTelemetry spans to Postgres
    # (agno_traces / agno_spans tables) so AgentOS shows every run's tree.
    # The Agno Viz bridge is additive and needs the AGNO_VIZ_* pair.
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

    # Copilot skills
    SKILLS_ENABLED: bool = True
    SKILLS_PATH: str = ""  # empty = skills/ at the repo root

    # Approval experience
    APPROVAL_REMINDER_HOURS: int = 24
    APPROVAL_TTL_HOURS: int = 72
    APPROVER_SLACK_IDS: str = ""  # comma-separated, empty = anyone in channel
    DEAL_DEFAULT_AMOUNT: str = ""
    DEAL_STAGE_DEFAULT: str = "prospecting"

    # Time. Every agent is told the date *with its weekday* in this zone, and
    # every scheduled job reads it; UTC is the honest default, not a guess.
    TIMEZONE: str = "UTC"

    # Digest
    DIGEST_HOUR: int = 8
    DIGEST_TZ: str = ""  # empty = TIMEZONE

    # AgentOS auth
    OS_SECURITY_KEY: str = ""

    @property
    def digest_tz(self) -> str:
        return self.DIGEST_TZ or self.TIMEZONE

    @property
    def icp_yaml_path(self) -> Path:
        if self.ICP_PATH:
            return Path(self.ICP_PATH)
        return Path(__file__).parent / "icp.yaml"

    @property
    def skills_dir_path(self) -> Path:
        if self.SKILLS_PATH:
            return Path(self.SKILLS_PATH)
        return Path(__file__).parent.parent / "skills"

    @property
    def approver_ids(self) -> set[str]:
        if not self.APPROVER_SLACK_IDS.strip():
            return set()
        return {uid.strip() for uid in self.APPROVER_SLACK_IDS.split(",") if uid.strip()}


settings = Settings()