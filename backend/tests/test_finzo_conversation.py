"""Voice conversation context and deterministic follow-up resolution.

These cover the Phase 8 requirement that "why?" and "what about shopping?"
resolve against prior turns WITHOUT depending on the LLM, so the tests assert on
the rewritten query text rather than on any model output.
"""
from __future__ import annotations

import time

import pytest

from voice.conversation import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TURNS,
    NEVER_TIMEOUT,
    SessionRegistry,
    detect_category,
    detect_metric,
)


@pytest.fixture
def registry():
    return SessionRegistry()


@pytest.fixture
def session(registry):
    return registry.get_or_create("u_test")


# ---- entity detection ----------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("how much did I spend on food", "Food"),
        ("what about groceries", "Food"),
        ("my swiggy orders", "Food"),
        ("what about shopping", "Shopping"),
        ("how much on amazon", "Shopping"),
        ("netflix cost", "Entertainment"),
        ("uber rides", "Travel"),
        ("my rent", "Housing"),
        ("electricity bills", "Utilities"),
        ("my salary", "Income"),
        ("how am I doing", None),
    ],
)
def test_detect_category(text, expected):
    assert detect_category(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("how much did I spend on food", "spending"),
        ("what is my health score", "health_score"),
        ("why did my score drop", "health_score"),
        ("what will I spend next month", "forecast"),
        ("how can I save more", "savings"),
        ("can I reduce that", "savings"),
        ("any unusual spending", "anomaly"),
        ("show me my subscriptions", "subscriptions"),
        ("hello there", None),
    ],
)
def test_detect_metric(text, expected):
    assert detect_metric(text) == expected


# ---- follow-up resolution ------------------------------------------------- #
def test_standalone_query_is_not_rewritten(session):
    query = "how much did i spend on food"
    assert session.resolve(query) == query


def test_what_about_carries_the_previous_metric(session):
    """Scenario 4: 'food spending' then 'what about shopping?'"""
    session.note_turn(
        text="how much did i spend on food",
        resolved_text="how much did i spend on food",
        intent="spending",
        response="You spent Rs.4,850 on food.",
        duration_ms=900,
    )
    assert session.last_category == "Food"
    assert session.last_metric == "spending"

    resolved = session.resolve("what about shopping")
    assert "Shopping" in resolved
    assert "spend" in resolved.lower()


def test_why_resolves_against_last_category(session):
    session.note_turn(
        text="how much did i spend on food",
        resolved_text="how much did i spend on food",
        intent="spending",
        response="You spent Rs.4,850 on food.",
        duration_ms=900,
    )
    resolved = session.resolve("why")
    assert "Food" in resolved
    assert "why" in resolved.lower()


def test_why_is_that_high_keeps_the_qualifier(session):
    session.note_turn(
        text="how much did i spend on food",
        resolved_text="how much did i spend on food",
        intent="spending",
        response="Rs.4,850",
        duration_ms=800,
    )
    resolved = session.resolve("why is that high")
    assert "Food" in resolved
    assert "high" in resolved


def test_why_with_no_prior_context_is_left_alone(session):
    """Nothing to resolve against: pass it through rather than inventing a topic."""
    assert session.resolve("why") == "why"


def test_pronoun_followup_references_last_subject(session):
    session.note_turn(
        text="what about shopping",
        resolved_text="how much did i spend on Shopping",
        intent="spending",
        response="Rs.8,200 on shopping.",
        duration_ms=850,
    )
    resolved = session.resolve("can i reduce that")
    assert "Shopping" in resolved
    assert "reduce" in resolved


def test_score_followup_phrasing(session):
    session.note_turn(
        text="what is my health score",
        resolved_text="what is my health score",
        intent="score",
        response="Your score is 72.",
        duration_ms=700,
    )
    assert session.last_metric == "health_score"
    resolved = session.resolve("why did it change")
    assert "health score" in resolved.lower()


def test_three_turn_chain_tracks_topic(session):
    """food -> shopping -> reduce: the topic must follow the switch."""
    session.note_turn(
        text="how much did i spend on food", resolved_text="how much did i spend on food",
        intent="spending", response="Rs.4,850", duration_ms=800,
    )
    q2 = session.resolve("what about shopping")
    session.note_turn(
        text="what about shopping", resolved_text=q2,
        intent="spending", response="Rs.8,200", duration_ms=800,
    )
    assert session.last_category == "Shopping", "topic should switch off Food"

    q3 = session.resolve("can i reduce it")
    assert "Shopping" in q3


# ---- timeout -------------------------------------------------------------- #
def test_default_timeout(session):
    assert session.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert not session.is_expired()


def test_session_expires_after_timeout(session):
    session.timeout_seconds = 10
    session.last_activity_at = time.time() - 11
    assert session.is_expired()


def test_touch_prevents_expiry(session):
    session.timeout_seconds = 10
    session.last_activity_at = time.time() - 11
    session.touch()
    assert not session.is_expired()


def test_never_timeout_does_not_expire(session):
    session.timeout_seconds = NEVER_TIMEOUT
    session.last_activity_at = time.time() - 100_000
    assert not session.is_expired()


def test_registry_issues_a_new_session_after_expiry(registry):
    first = registry.get_or_create("u_x")
    first.timeout_seconds = 10
    first.last_activity_at = time.time() - 11
    second = registry.get_or_create("u_x")
    assert second.voice_session_id != first.voice_session_id


def test_registry_reuses_a_live_session(registry):
    a = registry.get_or_create("u_y")
    b = registry.get_or_create("u_y")
    assert a.voice_session_id == b.voice_session_id


def test_sessions_are_isolated_per_user(registry):
    a = registry.get_or_create("u_a")
    b = registry.get_or_create("u_b")
    assert a.voice_session_id != b.voice_session_id
    a.note_turn(text="food", resolved_text="food", intent="spending",
                response="x", duration_ms=1)
    assert b.last_category is None, "one user's context must not leak into another"


def test_end_session(registry):
    registry.get_or_create("u_z")
    assert registry.end("u_z") is True
    assert registry.end("u_z") is False


# ---- turn log ------------------------------------------------------------- #
def test_turn_log_records_metadata(session):
    turn = session.note_turn(
        text="how much on food", resolved_text="how much on food",
        intent="spending", response="Rs.4,850", duration_ms=1234,
    )
    assert turn.duration_ms == 1234
    assert turn.status == "ok"
    assert session.snapshot()["turns"][-1]["intent"] == "spending"


def test_turn_log_is_capped(session):
    for i in range(MAX_TURNS + 15):
        session.note_turn(text=f"q{i}", resolved_text=f"q{i}", intent="spending",
                          response="r", duration_ms=1)
    assert len(session.turns) == MAX_TURNS


def test_failed_turn_does_not_poison_context(session):
    session.note_turn(text="how much on food", resolved_text="how much on food",
                      intent="spending", response="Rs.4,850", duration_ms=10)
    session.note_turn(text="garbled noise", resolved_text="garbled noise",
                      intent="unknown", response="", duration_ms=10, status="error")
    assert session.last_category == "Food", "an errored turn must not clear context"


def test_snapshot_contains_no_audio(session):
    """Privacy: the session must never carry raw audio."""
    session.note_turn(text="hi", resolved_text="hi", intent="spending",
                      response="hello", duration_ms=5)
    blob = repr(session.snapshot())
    for banned in ("audio", "wav", "webm", "bytes"):
        assert banned not in blob.lower()


def test_reset_context_keeps_session_identity(session):
    session.note_turn(text="food", resolved_text="food", intent="spending",
                      response="x", duration_ms=1)
    sid = session.voice_session_id
    session.reset_context()
    assert session.last_category is None
    assert session.voice_session_id == sid
