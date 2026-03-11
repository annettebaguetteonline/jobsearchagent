"""Applikationskonfiguration via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(name: str) -> str | None:
    """Lese einen Docker-Secret aus /run/secrets/<name>."""
    secret_path = Path(f"/run/secrets/{name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "development"
    log_level: str = "INFO"
    db_path: Path = Path("./data/jobs.db")
    chroma_path: Path = Path("./data/chroma")

    # Ollama — muss an 127.0.0.1 gebunden sein
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model_stage1: str = "mistral-nemo:12b"
    ollama_embed_model: str = "nomic-embed-text"

    home_address: str = "Frankfurt, Germany"
    max_commute_min: int = 60

    @property
    def anthropic_api_key(self) -> str:
        """Lese Anthropic-Key aus Docker-Secret — niemals aus Umgebungsvariablen."""
        key = _read_secret("anthropic_key")
        if not key:
            raise RuntimeError(
                "Anthropic-API-Key nicht gefunden unter /run/secrets/anthropic_key. "
                "Bitte infrastructure/secrets/anthropic_key.txt anlegen."
            )
        return key


settings = Settings()
