"""Production secrets fail-fast validation (backend/app/core/config.py).

When ENVIRONMENT=production the app must refuse to start if any required
secret is missing or left at its insecure dev default. These tests exercise
the Settings validator directly (not the lru-cached get_settings()).
"""

import pytest

from app.core.config import Settings

_DEV_DB_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/stayflow_test"

_PROD_SECRETS = {
    "JWT_SECRET_KEY": "a" * 64,
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "TELEGRAM_WEBHOOK_SECRET": "b" * 64,
    "TWILIO_ACCOUNT_SID": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "TWILIO_AUTH_TOKEN": "c" * 32,
    # agent_provider now defaults to "inception", so a production deploy
    # needs this unless it explicitly opts into another provider.
    "INCEPTION_API_KEY": "d" * 40,
}

# Every env var the Settings model reads that these tests care about, so a
# test can start from a clean slate regardless of ambient environment.
_MANAGED_VARS = [
    "ENVIRONMENT",
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_NUMBER",
    "LLM_PROVIDER",
    "AGENT_PROVIDER",
    "INCEPTION_API_KEY",
]


def _clean_env(monkeypatch):
    for var in _MANAGED_VARS:
        monkeypatch.delenv(var, raising=False)


def _prod_env(monkeypatch, **overrides):
    """Set a fully valid production environment, then apply overrides.

    An override value of None removes the variable (simulates "missing").
    """
    _clean_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", _DEV_DB_URL)
    for var, value in _PROD_SECRETS.items():
        monkeypatch.setenv(var, value)
    for var, value in overrides.items():
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)


def test_production_default_jwt_secret_raises(monkeypatch):
    _prod_env(monkeypatch, JWT_SECRET_KEY=None)  # fall back to dev default
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings()


def test_production_missing_telegram_webhook_secret_raises(monkeypatch):
    _prod_env(monkeypatch, TELEGRAM_WEBHOOK_SECRET=None)
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        Settings()


def test_production_missing_twilio_auth_token_raises(monkeypatch):
    _prod_env(monkeypatch, TWILIO_AUTH_TOKEN=None)
    with pytest.raises(ValueError, match="TWILIO_AUTH_TOKEN"):
        Settings()


def test_production_missing_telegram_bot_token_raises(monkeypatch):
    _prod_env(monkeypatch, TELEGRAM_BOT_TOKEN=None)
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        Settings()


def test_production_blank_secret_counts_as_missing(monkeypatch):
    _prod_env(monkeypatch, TWILIO_AUTH_TOKEN="   ")
    with pytest.raises(ValueError, match="TWILIO_AUTH_TOKEN"):
        Settings()


def test_production_all_secrets_set_passes(monkeypatch):
    _prod_env(monkeypatch)
    settings = Settings()
    assert settings.environment == "production"


def test_production_inception_provider_requires_api_key(monkeypatch):
    _prod_env(monkeypatch, LLM_PROVIDER="inception", INCEPTION_API_KEY=None)
    with pytest.raises(ValueError, match="INCEPTION_API_KEY"):
        Settings()


def test_production_inception_provider_with_key_passes(monkeypatch):
    # Default provider is inception (agent_provider default); key set → OK.
    _prod_env(monkeypatch)
    assert Settings().environment == "production"


def test_production_mock_provider_does_not_need_inception_key(monkeypatch):
    _prod_env(monkeypatch, LLM_PROVIDER="mock", INCEPTION_API_KEY=None)
    assert Settings().environment == "production"


def test_production_sqlite_database_url_raises(monkeypatch):
    _prod_env(monkeypatch, DATABASE_URL="sqlite:///./stayflow.db")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings()


def test_non_production_does_not_raise(monkeypatch):
    # Dev/test environments keep working with unset secrets and the dev
    # JWT default.
    _clean_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", _DEV_DB_URL)
    settings = Settings()
    assert settings.environment == "development"


def test_error_message_names_variable_and_fix_without_leaking_values(monkeypatch):
    canary = "canary-secret-value-0000"
    _prod_env(monkeypatch, TELEGRAM_BOT_TOKEN=canary, TELEGRAM_WEBHOOK_SECRET=None)
    with pytest.raises(ValueError) as exc_info:
        Settings()
    message = str(exc_info.value)
    assert "TELEGRAM_WEBHOOK_SECRET" in message
    assert "openssl rand -hex 32" in message
    assert canary not in message
