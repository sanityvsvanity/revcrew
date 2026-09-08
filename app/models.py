"""Model factory: one place where providers are chosen (D11, S7.1–S7.3).

Agents ask for a *role*, never a model id. Provider selection is static config.
No Ollama config ⇒ pure Anthropic, exactly today's behavior.

`get_fallback_model(role)` hands callers an Anthropic instance for a one-shot
retry when an Ollama step fails (see `_classify_reply_step`); steps that run
inside agno workflows adopt it as they're wired for S7.3.
"""

from __future__ import annotations

import logging
from typing import Any

from agno.models.anthropic import Claude
from agno.models.base import Model

from app.config import settings

logger = logging.getLogger(__name__)

# Role → Anthropic model mapping (existing behavior)
_ROLE_ANTHROPIC_MAP: dict[str, str] = {
    "researcher": settings.MODEL_MAIN,
    "qualifier": settings.MODEL_FAST,
    "outreach_writer": settings.MODEL_MAIN,
    "crm_scribe": settings.MODEL_FAST,
    "copilot": settings.MODEL_MAIN,
    "triage": settings.MODEL_FAST,
}

# Role → Ollama model mapping
_ROLE_OLLAMA_MAP: dict[str, str] = {
    "researcher": settings.OLLAMA_MODEL_MAIN,
    "qualifier": settings.OLLAMA_MODEL_FAST,
    "outreach_writer": settings.OLLAMA_MODEL_MAIN,
    "crm_scribe": settings.OLLAMA_MODEL_FAST,
    "copilot": settings.OLLAMA_MODEL_MAIN,
    "triage": settings.OLLAMA_MODEL_FAST,
}


def _ollama_configured() -> bool:
    """Return True if Ollama is configured (host or API key set)."""
    return bool(settings.OLLAMA_HOST or settings.OLLAMA_API_KEY)


def _resolve_provider() -> str:
    """Resolve the effective provider from MODEL_PROVIDER config."""
    provider = settings.MODEL_PROVIDER.lower()
    if provider == "auto":
        return "ollama" if _ollama_configured() else "anthropic"
    if provider in ("anthropic", "ollama"):
        return provider
    logger.warning("Unknown MODEL_PROVIDER '%s', falling back to anthropic", provider)
    return "anthropic"


def get_model(role: str) -> Model:
    """Return a model instance for the given role.

    Roles: researcher, qualifier, outreach_writer, crm_scribe, copilot, triage.

    Selection per D11:
    - MODEL_PROVIDER=auto: Ollama if configured, else Anthropic
    - MODEL_PROVIDER=anthropic: always Anthropic
    - MODEL_PROVIDER=ollama: always Ollama (fails if not configured)
    """
    provider = _resolve_provider()

    if provider == "ollama":
        if not _ollama_configured():
            raise RuntimeError(
                "MODEL_PROVIDER=ollama but OLLAMA_HOST and OLLAMA_API_KEY are both empty. "
                "Set OLLAMA_HOST or OLLAMA_API_KEY, or switch to MODEL_PROVIDER=anthropic."
            )
        return _build_ollama_model(role)

    # Anthropic (default)
    model_id = _ROLE_ANTHROPIC_MAP.get(role, settings.MODEL_MAIN)
    return Claude(id=model_id)


def _build_ollama_model(role: str) -> Model:
    """Build an Ollama model instance for the given role.

    agno 2.5.17 Ollama class: from agno.models.ollama import Ollama
    Constructor: Ollama(id=..., host=..., api_key=...)
    """
    from agno.models.ollama import Ollama

    model_id = _ROLE_OLLAMA_MAP.get(role, settings.OLLAMA_MODEL_MAIN)
    kwargs: dict[str, Any] = {"id": model_id}

    if settings.OLLAMA_HOST:
        kwargs["host"] = settings.OLLAMA_HOST
    elif settings.OLLAMA_API_KEY:
        # ollama.cloud: host defaults to https://ollama.com when API key is set
        kwargs["host"] = "https://ollama.com"
        kwargs["api_key"] = settings.OLLAMA_API_KEY

    if is_ollama_cloud():
        # Ollama Cloud returns HTTP 200 and silently drops the API-level
        # structured-output parameter (measured 2026-07-31 on qwen/glm/nemotron
        # by the predecessor system; its LESSONS P36). agno trusts the class
        # flag and never engages its own JSON-in-prompt fallback, so every
        # output_schema agent would fail on attempt 1. Flipping the flag puts
        # the schema in the prompt and parses the text — verified to return
        # real Pydantic objects on those models.
        kwargs["supports_native_structured_outputs"] = False
        kwargs["supports_json_schema_outputs"] = False

    return Ollama(**kwargs)


def is_ollama_cloud() -> bool:
    """True when Ollama requests go to ollama.com (hosted) rather than a local daemon."""
    if settings.OLLAMA_HOST:
        return "ollama.com" in settings.OLLAMA_HOST
    return bool(settings.OLLAMA_API_KEY)


def pipeline_agent_kwargs() -> dict[str, Any]:
    """Shared constructor kwargs for the four single-purpose pipeline agents.

    - No history and no memory: a pipeline agent starts every run from its
      input and its tools. A research agent that replayed prior runs once booted
      at 145K prompt tokens with another prospect's facts in context.
    - The date arrives labelled. ``add_datetime_to_context`` with a format that
      spells the weekday means the model never does calendar arithmetic; the
      predecessor answered "Sun Sep 7" for a Monday when it was handed digits.
    """
    return {
        "add_history_to_context": False,
        "num_history_runs": 0,
        "add_datetime_to_context": True,
        "datetime_format": "%A %d %B %Y, %H:%M %Z",
        "timezone_identifier": settings.TIMEZONE,
        "markdown": False,
    }


def has_anthropic_fallback() -> bool:
    """Return True if Anthropic fallback is available (API key set)."""
    return bool(settings.ANTHROPIC_API_KEY)


def get_fallback_model(role: str) -> Model | None:
    """Return an Anthropic model for fallback, or None if not available."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    model_id = _ROLE_ANTHROPIC_MAP.get(role, settings.MODEL_MAIN)
    return Claude(id=model_id)