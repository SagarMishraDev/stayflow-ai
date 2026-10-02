"""Agent configuration, read from the application settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.agent.providers.base import LLMProvider
from app.agent.providers.mock import MockProvider

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass
class AgentConfig:
    # Production default is the real Inception/Mercury provider. The mock
    # provider is an explicit opt-in (LLM_PROVIDER=mock) for tests and demos.
    provider_name: str = "inception"
    model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"
    timeout_seconds: int = 120
    temperature: float = 0.2
    max_iterations: int = 8
    history_limit: int = 20
    inception_api_key: str | None = None
    inception_model: str = "mercury-2.5"
    inception_base_url: str = "https://api.inceptionlabs.ai/v1"
    inception_timeout_seconds: int = 120
    inception_max_retries: int = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentConfig:
        """Build an AgentConfig from the application settings.

        ``llm_provider`` takes precedence; when it is unset the legacy
        ``agent_provider`` applies, so existing deployments keep working.
        """
        return cls(
            provider_name=settings.llm_provider or settings.agent_provider,
            model=settings.agent_model,
            ollama_base_url=settings.agent_ollama_base_url,
            timeout_seconds=settings.agent_timeout_seconds,
            temperature=settings.agent_temperature,
            max_iterations=settings.agent_max_iterations,
            history_limit=settings.agent_history_limit,
            inception_api_key=settings.inception_api_key,
            inception_model=settings.inception_model,
            inception_base_url=settings.inception_base_url,
            inception_timeout_seconds=settings.inception_timeout_seconds,
            inception_max_retries=settings.inception_max_retries,
        )


def build_provider(config: AgentConfig, script: list | None = None) -> LLMProvider:
    """Instantiate the configured provider.

    ``script`` is only honored by the mock provider and exists for tests.
    """
    if config.provider_name == "ollama":
        from app.agent.providers.ollama import OllamaProvider

        return OllamaProvider(
            model=config.model,
            base_url=config.ollama_base_url,
            timeout_seconds=config.timeout_seconds,
            temperature=config.temperature,
        )
    if config.provider_name == "inception":
        from app.agent.providers.inception import InceptionProvider

        # Fail fast with a clear error instead of silently falling back to
        # another provider: LLM_PROVIDER=inception requires a key, or an
        # explicit LLM_PROVIDER=mock opt-in for tests/demos.
        if not config.inception_api_key:
            raise ValueError(
                "LLM_PROVIDER=inception requires INCEPTION_API_KEY to be set. "
                "Set INCEPTION_API_KEY, or set LLM_PROVIDER=mock explicitly "
                "for tests/demos."
            )
        return InceptionProvider(
            api_key=config.inception_api_key,
            model=config.inception_model,
            base_url=config.inception_base_url,
            timeout_seconds=config.inception_timeout_seconds,
            temperature=config.temperature,
            max_retries=config.inception_max_retries,
        )
    if config.provider_name == "mock":
        return MockProvider(script=script)
    raise ValueError(f"Unknown agent provider: {config.provider_name}")
