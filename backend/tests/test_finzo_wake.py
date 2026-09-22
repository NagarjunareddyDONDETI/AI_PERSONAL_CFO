"""Wake-phrase recognition for Finzo.

False activations matter more than missed ones here: the microphone is always on
in hands-free mode, so a matcher that fires on "financial" would interrupt the
user mid-sentence. The rejection tests are therefore as important as the
acceptance tests.
"""
from __future__ import annotations

import pytest

from voice.wake import (
    WAKE_WORD,
    is_stop_command,
    match_wake_word,
    normalize,
    strip_wake_word,
)


# ---- normalisation -------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Finzo", "finzo"),
        ("  Finzo  ", "finzo"),
        ("Finzo!", "finzo"),
        ("Finzo,", "finzo"),
        ("Finzo.", "finzo"),
        ("FINZO?", "finzo"),
        ("Hey    Finzo", "hey finzo"),
        ("Hey-Finzo", "hey finzo"),
        ("", ""),
        ("   ", ""),
        ("How much did I spend on food?", "how much did i spend on food"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# ---- accepted wake phrases ------------------------------------------------ #
@pytest.mark.parametrize(
    "utterance",
    [
        "Finzo",
        "finzo",
        "FINZO",
        "Finzo!",
        "Finzo?",
        "  finzo  ",
        "Hey Finzo",
        "hey finzo",
        "Hey, Finzo!",
        "Okay Finzo",
        "okay finzo",
        "OK Finzo",
        "Hello Finzo",
        "Hi Finzo",
        "Yo Finzo",
    ],
)
def test_wake_variants_activate(utterance):
    assert match_wake_word(utterance).matched, f"{utterance!r} should activate"


def test_exact_match_is_reported_as_exact():
    match = match_wake_word("Hey Finzo")
    assert match.kind == "exact"
    assert match.matched_token == WAKE_WORD


@pytest.mark.parametrize("heard", ["fizzo", "finso", "fonzo", "finzo"])
def test_close_mishearings_still_activate(heard):
    """Speech recognisers rarely return an unusual product name perfectly."""
    assert match_wake_word(heard).matched, f"{heard!r} should activate"


# ---- rejected speech ------------------------------------------------------ #
@pytest.mark.parametrize(
    "utterance",
    [
        # The exact false positives called out in the requirements.
        "financial",
        "Fins",
        "Fernando",
        "finance",
        # Substring traps: these all contain "fin".
        "financial planning",
        "my finances",
        "financially stable",
        "final answer",
        "finally",
        "finish",
        # Ordinary questions that must never self-trigger.
        "How much did I spend on food?",
        "What is my health score",
        "Show me my subscriptions",
        # Empty / noise.
        "",
        "   ",
        "uh",
        "hmm",
    ],
)
def test_unrelated_speech_does_not_activate(utterance):
    assert not match_wake_word(utterance).matched, f"{utterance!r} must NOT activate"


def test_wake_word_mid_sentence_is_ignored():
    """Position anchoring: talking *about* Finzo is not addressing Finzo."""
    assert not match_wake_word("I was reading about Finzo yesterday").matched
    assert not match_wake_word("my accountant said finzo is fine").matched


def test_non_greeting_prefix_is_rejected():
    """Only greetings may precede the wake word."""
    assert not match_wake_word("tell finzo about it").matched
    assert match_wake_word("hey finzo").matched


# ---- query captured in the same breath ------------------------------------ #
def test_query_in_same_breath_is_extracted():
    match = match_wake_word("Finzo, how much did I spend on food?")
    assert match.matched
    assert match.query == "how much did i spend on food"


def test_query_extracted_after_greeting():
    match = match_wake_word("Hey Finzo what is my health score")
    assert match.matched
    assert match.query == "what is my health score"


def test_bare_wake_word_has_no_query():
    assert match_wake_word("Finzo").query == ""


def test_strip_wake_word():
    assert strip_wake_word("Finzo, what about shopping?") == "what about shopping"
    # No wake word present: pass the (normalised) query straight through, which
    # is what conversation mode needs for follow-ups.
    assert strip_wake_word("What about shopping?") == "what about shopping"


# ---- barge-in / stop ------------------------------------------------------ #
@pytest.mark.parametrize(
    "utterance",
    ["stop", "Stop.", "STOP", "wait", "Wait!", "cancel", "hold on", "never mind",
     "quiet", "enough", "Finzo stop", "hey finzo cancel"],
)
def test_stop_commands_detected(utterance):
    assert is_stop_command(utterance), f"{utterance!r} should stop playback"


@pytest.mark.parametrize(
    "utterance",
    [
        # Contains "stop" but is a genuine question - cutting the answer off here
        # would be a bug.
        "how do I stop overspending",
        "should I stop my Netflix subscription",
        "what about shopping",
        "why is that high",
        "",
    ],
)
def test_questions_containing_stop_are_not_interruptions(utterance):
    assert not is_stop_command(utterance), f"{utterance!r} must not stop playback"
