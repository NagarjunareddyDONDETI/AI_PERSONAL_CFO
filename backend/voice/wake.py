"""Wake-phrase recognition for the Finzo hands-free assistant.

Pure text matching, no audio and no I/O, so the activation rules are fully
unit-testable without a microphone. The audio path that produces `text` lives in
the browser (on-device speech recognition) and in ``voice/stt`` (Whisper).

Design priority is FEWER FALSE ACTIVATIONS over catching every mumble. The
microphone is always on in hands-free mode, so a matcher that fires on
"financial" would make the assistant interrupt the user constantly. Three
independent guards enforce that:

  1. An explicit deny list of real English words that sound close to "finzo".
  2. Token-exact or edit-distance-1 matching, never substring matching --
     substring is what makes "financial" match "fin".
  3. Position anchoring: the wake token must appear within the first few tokens,
     optionally after a greeting ("hey", "okay"). Mid-sentence mentions are
     ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

WAKE_WORD = "finzo"

# Greetings allowed to precede the wake word: "hey finzo", "okay finzo".
_LEAD_INS = frozenset({"hey", "hi", "hello", "ok", "okay", "yo", "hay", "hei"})

# How far into an utterance the wake word may appear. Anything later is treated
# as the user talking *about* something, not addressing the assistant.
_MAX_LEAD_TOKENS = 3

# Real words close enough to "finzo" to be caught by fuzzy matching but common
# enough in financial conversation that matching them would be intolerable.
# Checked before fuzzy matching, so raising _MAX_EDIT_DISTANCE stays safe.
_DENY = frozenset(
    {
        "fin", "fins", "fine", "fined", "finer", "final", "finale", "finally",
        "finance", "financed", "finances", "financial", "financially",
        "finish", "finished", "finishing", "fernando", "fernanda",
        "info", "inzo", "zero", "window", "windows", "five", "font",
    }
)

# Allow one character of slop, which covers the realistic mishearings
# ("fizzo", "finso", "fonzo") without reaching real words. At distance 2,
# "fins" and "into" would both match, which is why this stays at 1.
_MAX_EDIT_DISTANCE = 1

# Phrases that stop playback mid-answer (barge-in). Kept here with the other
# phrase matching rather than in the session module.
_STOP_PHRASES = frozenset(
    {"stop", "stop it", "wait", "hold on", "cancel", "quiet", "shut up",
     "never mind", "nevermind", "enough", "shush", "pause"}
)

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Speech recognisers punctuate inconsistently -- "Finzo," / "Finzo." / "finzo"
    are the same utterance and must normalise identically.
    """
    if not text:
        return ""
    lowered = text.lower().replace("-", " ")
    stripped = _PUNCT_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", stripped).strip()


def _edit_distance(a: str, b: str, *, cap: int) -> int:
    """Levenshtein distance, abandoned early once it exceeds `cap`.

    Rolling two-row implementation: the full matrix is never needed because only
    the previous row is read, and bailing out early keeps the always-on wake
    listener cheap.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,          # deletion
                    current[j - 1] + 1,       # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        if min(current) > cap:
            return cap + 1
        previous = current
    return previous[-1]


def _token_is_wake(token: str) -> tuple[bool, bool]:
    """Return (is_wake, is_exact) for a single normalised token."""
    if not token or token in _DENY:
        return False, False
    if token == WAKE_WORD:
        return True, True
    if _edit_distance(token, WAKE_WORD, cap=_MAX_EDIT_DISTANCE) <= _MAX_EDIT_DISTANCE:
        return True, False
    return False, False


@dataclass(frozen=True)
class WakeMatch:
    """Outcome of testing one utterance for the wake phrase."""

    matched: bool
    #: The token that actually matched, e.g. "finzo" or a near-miss like "fizzo".
    matched_token: str | None = None
    #: Anything said after the wake word in the same breath. Lets
    #: "Finzo, how much did I spend on food" skip straight to the query
    #: instead of prompting the user to repeat themselves.
    query: str = ""
    #: "exact" when heard verbatim, "fuzzy" when accepted within edit distance.
    kind: str = ""

    def __bool__(self) -> bool:  # allows `if match:`
        return self.matched


NO_MATCH = WakeMatch(matched=False)


def match_wake_word(text: str) -> WakeMatch:
    """Test an utterance for the Finzo wake phrase.

    Accepts "Finzo", "finzo", "Hey Finzo", "Okay Finzo!" and the same phrase with
    a query attached. Rejects unrelated speech and words such as "financial",
    "finance", "fins" and "Fernando".
    """
    normalized = normalize(text)
    if not normalized:
        return NO_MATCH

    tokens = normalized.split(" ")
    limit = min(len(tokens), _MAX_LEAD_TOKENS)

    for index in range(limit):
        # Only a greeting may sit in front of the wake word; any other leading
        # word means this is ordinary speech that happens to contain the name.
        if index and any(t not in _LEAD_INS for t in tokens[:index]):
            break

        is_wake, is_exact = _token_is_wake(tokens[index])
        if not is_wake:
            continue

        trailing = " ".join(tokens[index + 1:]).strip()
        return WakeMatch(
            matched=True,
            matched_token=tokens[index],
            query=trailing,
            kind="exact" if is_exact else "fuzzy",
        )

    return NO_MATCH


def is_stop_command(text: str) -> bool:
    """True when the user is interrupting to stop playback.

    Deliberately whole-utterance matching: "stop" on its own is an interruption,
    but "how do I stop overspending" is a question and must not cut the answer
    off.
    """
    normalized = normalize(text)
    if not normalized:
        return False
    if normalized in _STOP_PHRASES:
        return True
    # "finzo stop" / "hey finzo stop" -- addressed interruption.
    match = match_wake_word(normalized)
    return bool(match) and match.query in _STOP_PHRASES


def strip_wake_word(text: str) -> str:
    """Remove a leading wake phrase, returning just the query.

    Returns the normalised input unchanged when no wake phrase is present, so
    this is safe to call on every utterance during conversation mode.
    """
    match = match_wake_word(text)
    return match.query if match.matched else normalize(text)
