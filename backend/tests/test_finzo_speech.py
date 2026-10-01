"""Written-to-spoken rewriting for Finzo voice answers.

The critical invariant: figures must survive untouched. Every number the copilot
produces comes from deterministic backend calculations, so a formatting pass that
rounds, drops or mangles one would be a correctness bug, not a cosmetic one.
"""
from __future__ import annotations

import random

import pytest

from voice.speech import (
    ACKNOWLEDGEMENTS,
    acknowledgement,
    error_speech,
    flatten_lists,
    flatten_tables,
    for_speech,
    limit_sentences,
    speakable_numbers,
    strip_markdown,
)


# ---- markdown ------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("**Food** spending", "Food spending"),
        ("*Food* spending", "Food spending"),
        ("__Food__ spending", "Food spending"),
        ("***Food***", "Food"),
        ("`code`", "code"),
        ("# Heading", "Heading"),
        ("### Heading", "Heading"),
        ("> quoted", "quoted"),
        ("[link text](http://x.com)", "link text"),
        ("plain text", "plain text"),
        ("", ""),
    ],
)
def test_strip_markdown(raw, expected):
    assert strip_markdown(raw).strip() == expected


# ---- currency and percent ------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Rs.4,850", "4,850 rupees"),
        ("Rs 4,850", "4,850 rupees"),
        ("Rs4850", "4850 rupees"),
        ("₹4,850", "4,850 rupees"),
        ("INR 4,850", "4,850 rupees"),
        ("16%", "16 percent"),
        ("16.5%", "16.5 percent"),
        ("22 %", "22 percent"),
    ],
)
def test_speakable_numbers(raw, expected):
    assert speakable_numbers(raw) == expected


def test_digits_are_never_altered():
    """The figure itself must pass through byte-for-byte."""
    out = speakable_numbers("You spent Rs.4,850 on food, which is 16% of Rs.30,312.")
    assert "4,850" in out
    assert "30,312" in out
    assert "16" in out


def test_currency_inside_a_sentence():
    out = for_speech("You spent **Rs.4,850** on food last month.")
    assert out == "You spent 4,850 rupees on food last month."


# ---- lists ---------------------------------------------------------------- #
def test_flatten_bullet_list():
    out = flatten_lists("- Amazon\n- Swiggy\n- Netflix")
    assert out == "Amazon, Swiggy, and Netflix."


def test_flatten_two_item_list():
    assert flatten_lists("- Amazon\n- Swiggy") == "Amazon and Swiggy."


def test_flatten_list_with_lead_in():
    out = flatten_lists("Savings suggestions:\n- Cut food\n- Cut travel")
    assert out == "Savings suggestions: Cut food and Cut travel."


def test_flatten_numbered_list():
    out = flatten_lists("1. First\n2. Second\n3. Third")
    assert out == "First, Second, and Third."


def test_no_bullets_is_unchanged():
    assert flatten_lists("just a sentence") == "just a sentence"


# ---- tables --------------------------------------------------------------- #
def test_flatten_table_to_speech():
    table = (
        "| Merchant | Amount |\n"
        "|---|---|\n"
        "| Amazon | 8000 |\n"
        "| Swiggy | 3500 |\n"
        "| Netflix | 649 |"
    )
    out = flatten_tables(table)
    assert "|" not in out, "pipes must never reach TTS"
    assert "Amazon: 8000" in out
    assert "Swiggy: 3500" in out
    # Header row carries no digits and should have been dropped.
    assert "Merchant: Amount" not in out


def test_table_without_pipes_is_unchanged():
    assert flatten_tables("no table here") == "no table here"


def test_full_pipeline_on_a_table_answer():
    written = (
        "Your biggest expenses:\n\n"
        "| Merchant | Amount |\n|---|---|\n"
        "| Amazon | Rs.8,000 |\n| Swiggy | Rs.3,500 |"
    )
    out = for_speech(written)
    assert "|" not in out
    assert "-" not in out.replace("Mm-hm", "")
    assert "8,000 rupees" in out
    assert "3,500 rupees" in out


# ---- length --------------------------------------------------------------- #
def test_limit_sentences():
    text = "One. Two. Three. Four. Five."
    assert limit_sentences(text, 2) == "One. Two."


def test_limit_sentences_keeps_short_answers_whole():
    assert limit_sentences("Only one.", 3) == "Only one."


def test_limit_zero_is_a_noop():
    assert limit_sentences("One. Two.", 0) == "One. Two."


def test_for_speech_caps_long_answers():
    written = " ".join(f"Sentence {i}." for i in range(10))
    out = for_speech(written, max_sentences=3)
    assert out.count(".") == 3


def test_for_speech_handles_empty_input():
    assert for_speech("") == ""
    assert for_speech("   ") == ""


def test_for_speech_collapses_newlines():
    out = for_speech("Line one.\n\n\nLine two.")
    assert "\n" not in out
    assert out == "Line one. Line two."


# ---- acknowledgements ----------------------------------------------------- #
def test_acknowledgement_is_from_the_controlled_set():
    for _ in range(30):
        assert acknowledgement() in ACKNOWLEDGEMENTS


def test_acknowledgements_vary():
    """Requirement: do not use the same acknowledgement every time."""
    rng = random.Random(7)
    seen = {acknowledgement(rng) for _ in range(40)}
    assert len(seen) > 1


def test_acknowledgements_are_short():
    """Long acknowledgements defeat the point of a fast reply."""
    for ack in ACKNOWLEDGEMENTS:
        assert len(ack) <= 24, ack


# ---- errors --------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code", ["NO_SPEECH", "EMPTY_AUDIO", "STT_FAILED", "LLM_FAILED", "NO_DATA"]
)
def test_error_speech_has_a_message(code):
    assert error_speech(code)


def test_unknown_error_code_falls_back():
    assert error_speech("SOMETHING_NEW") == error_speech("INTERNAL")


def test_error_speech_mentions_ai_service_for_llm_failure():
    assert "AI service" in error_speech("LLM_FAILED")


# ---- spoken length budget --------------------------------------------------- #
# The exact answer that ran to 47 seconds of speech on Voicebox.
_LONG_REAL_ANSWER = (
    "Last month (August 2026) you earned 21,925 rupees and spent 20,476.5 rupees, "
    "leaving a net 1,448 rupees surplus (about a 6.6 percent savings rate). Your "
    "biggest outflow was Uncategorized at 19,618.5 rupees, with smaller amounts for "
    "Food (133 rupees), Utilities (696 rupees), Travel (28 rupees) and a single 1 "
    "rupees entertainment purchase. The health score stayed at 20, putting you in "
    "the \u201cat\u2011risk\u201d zone and giving you only 0.07 months of "
    "emergency\u2011fund coverage."
)


def test_long_answer_is_cut_to_the_spoken_budget():
    from voice.speech import MAX_SPOKEN_CHARS

    out = for_speech(_LONG_REAL_ANSWER)
    assert len(out) <= MAX_SPOKEN_CHARS
    # The answer itself survives intact, figures and all.
    assert out.startswith("Last month (August 2026) you earned 21,925 rupees")
    assert "20,476.5" in out and out.endswith(".")


def test_budget_never_cuts_inside_a_sentence():
    out = for_speech("First part. " + "Second sentence is fine. " * 3, max_chars=40)
    assert out == "First part. Second sentence is fine."


def test_first_sentence_is_kept_even_if_over_budget():
    long_first = "You spent " + "a lot " * 80 + "on food."
    assert for_speech(long_first + " Second.", max_chars=50) == long_first


def test_char_budget_can_be_disabled():
    assert for_speech(_LONG_REAL_ANSWER, max_sentences=0, max_chars=0).count(".") >= 3


def test_unicode_hyphens_become_plain():
    assert "\u2011" not in for_speech("You are at\u2011risk.")


def test_streamer_respects_the_char_budget():
    from voice.speech import SentenceStreamer

    streamer = SentenceStreamer(max_sentences=4, max_chars=120)
    spoken = []
    for i in range(0, len(_LONG_REAL_ANSWER), 7):  # token-sized deltas
        spoken += streamer.feed(_LONG_REAL_ANSWER[i:i + 7])
    spoken += streamer.flush()
    assert len(spoken) == 1 and spoken[0].startswith("Last month (August 2026)")
