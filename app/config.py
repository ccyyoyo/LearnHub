"""Application settings, loaded from environment / .env (NFR-6)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All secrets/config are injected via environment variables (or a local
    ``.env`` file) so nothing is hard-coded in the source (NFR-6).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # YouTube Data API v3 key. Public playlists only need an API key, no OAuth
    # (see PRD §7.1). Import endpoints surface a friendly error when it's unset.
    youtube_api_key: str = ""

    # SQLite database location (single file — NFR-1).
    database_url: str = "sqlite:///learnhub.db"

    # Phase 3 (AI). ``llm_provider`` is a seam: only "claude" is wired today, but
    # routers go through it so a second provider (e.g. OpenRouter) can be added
    # later without touching them. AI endpoints surface a friendly error when the
    # key is unset, mirroring the YouTube path.
    anthropic_api_key: str = ""
    llm_provider: str = "claude"
    llm_model: str = "claude-sonnet-4-6"


@lru_cache
def get_settings() -> Settings:
    return Settings()
