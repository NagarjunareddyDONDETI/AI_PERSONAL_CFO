"""Phase 8 tests: model-routing preferred-provider override + selection."""
from __future__ import annotations

import pytest

from llm.router import LLMRouter


@pytest.fixture()
def router(monkeypatch):
    r = LLMRouter()
    # Make all providers appear available deterministically (no network/keys).
    monkeypatch.setattr(r, "available_providers", lambda: list(r.all_providers()))
    return r


# The intended failover chain. Pinned here because the order is a deliberate
# choice (cost and latency), not an implementation detail: several call sites and
# the /router/status ranking derive from it, and it has silently disagreed with
# the documentation before.
EXPECTED_CHAIN = ["groq", "github", "openrouter", "ollama", "gemini"]


def test_provider_chain_order(router):
    assert router.all_providers() == EXPECTED_CHAIN


def test_auto_selection_walks_the_chain_in_order(router, monkeypatch):
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)
    assert router._selection() == EXPECTED_CHAIN


def test_chain_order_is_preserved_when_a_provider_is_forced(router):
    """Forcing a provider promotes it without reshuffling the rest."""
    router.set_preferred("openrouter")
    assert router._selection() == [
        "openrouter", "groq", "github", "ollama", "gemini"
    ]


def test_unconfigured_providers_are_skipped_in_order(monkeypatch):
    r = LLMRouter()
    monkeypatch.setattr(r, "available_providers", lambda: ["github", "gemini"])
    # Relative order is kept; the missing ones are simply absent.
    assert r._selection() == ["github", "gemini"]


def test_default_preferred_is_auto(router, monkeypatch):
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)
    assert router.preferred() == "auto"
    # auto → full priority chain unchanged
    assert router._selection() == router.all_providers()


def test_set_preferred_moves_provider_first(router):
    assert router.set_preferred("gemini") == "gemini"
    sel = router._selection()
    assert sel[0] == "gemini"
    assert set(sel) == set(router.all_providers())  # rest remain as fallback


def test_set_preferred_auto_restores_chain(router):
    router.set_preferred("groq")
    router.set_preferred("auto")
    assert router.preferred() == "auto"
    assert router._selection() == router.all_providers()


def test_set_preferred_none_is_auto(router):
    router.set_preferred("groq")
    assert router.set_preferred(None) == "auto"


def test_set_preferred_rejects_unknown(router):
    with pytest.raises(ValueError):
        router.set_preferred("claude")


def test_runtime_override_beats_env(router, monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    router.set_preferred("groq")
    assert router.preferred() == "groq"
    assert router._selection()[0] == "groq"


def test_unavailable_preferred_falls_back_to_chain(monkeypatch):
    r = LLMRouter()
    # Only groq available; prefer gemini (unavailable) → chain stays as available.
    monkeypatch.setattr(r, "available_providers", lambda: ["groq"])
    r.set_preferred("gemini")
    assert r._selection() == ["groq"]
