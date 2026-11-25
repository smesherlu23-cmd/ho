"""Настройки: проверка значений и соответствие документации в .env.example."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
# Переменные, которые читают docker compose и nginx, а не бэкенд.
NOT_FOR_BACKEND = {
    "WHATEVER_PORT",
    "WHATEVER_BIND_ADDRESS",
    "WHATEVER_TRUSTED_PROXY",
    "WHATEVER_BACKUP_DIR",
    "WHATEVER_BACKUP_HOUR",
    "WHATEVER_BACKUP_KEEP_DAYS",
    "WHATEVER_IMAGE_PREFIX",
    "WHATEVER_VERSION",
}


def env_names() -> set[str]:
    """Имена переменных окружения, которые читает Settings."""
    prefix = Settings.model_config.get("env_prefix", "")
    return {
        (field.alias or f"{prefix}{name}").upper() for name, field in Settings.model_fields.items()
    }


def documented_names() -> set[str]:
    """Переменные из .env.example, в том числе закомментированные значения по умолчанию."""
    pattern = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)
    return set(pattern.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def test_env_example_documents_every_setting() -> None:
    assert documented_names() - NOT_FOR_BACKEND == env_names()


def test_password_with_special_characters_is_escaped_in_the_url() -> None:
    settings = Settings(postgres_password="p@ss/w:rd", postgres_host="db")
    url = settings.database_url
    assert url.password == "p@ss/w:rd"
    assert url.host == "db"
    assert "p@ss/w:rd" not in url.render_as_string(hide_password=True)


def test_database_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("WHATEVER_SESSION_TTL_DAYS", "0"),
        ("WHATEVER_SYNC_SAVE_DELAY_SECONDS", "-1"),
        ("WHATEVER_LOG_LEVEL", "LOUD"),
        ("WHATEVER_LOG_FORMAT", "xml"),
    ],
)
def test_invalid_values_are_rejected_at_startup(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError, match=variable.removeprefix("WHATEVER_").lower()):
        Settings()
