"""Turn written copilot answers into text worth listening to.

The copilot is tuned for a chat panel: it emits markdown, bullet lists and
"Rs.4,850". Read aloud, that becomes "asterisk asterisk Food colon dash R S dot
four thousand...". This module rewrites an answer for speech without touching the
figures themselves -- every number originates from deterministic backend
calculations and must survive unchanged.

Text-only transformation, so it is fully unit-testable with no audio involved.
"""
from __future__ import annotations

import random
import re

#: Short acknowledgements played the moment the wake word fires, so the user
#: hears something before the (slower) STT + LLM round trip begins. Randomised
#: from a controlled set -- the requirement is variety, not improvisation.
ACKNOWLEDGEMENTS: tuple[str, ...] = (
    "Yes?",
    "I'm listening.",
    "Go ahead.",
    "How can I help?",
    "Yes, I'm here.",
    "Mm-hm?",
)

#: Spoken when the user interrupts and there is nothing to say yet.
LISTENING_AGAIN = "Okay."

#: Voice-facing error lines. Kept short: a long apology read aloud is worse than
#: the failure it describes.
ERROR_SPEECH = {
    "NO_SPEECH": "Sorry, I didn't catch that. Please try again.",
    "EMPTY_AUDIO": "Sorry, I didn't catch that. Please try again.",
    "STT_FAILED": "Sorry, I couldn't make out what you said.",
    "STT_UNAVAILABLE": "Speech recognition isn't available right now.",
    "NO_DATA": "I don't have a statement to analyse yet. Upload one first.",
    "LLM_FAILED": "I'm having trouble reaching my AI service right now.",
    "INTERNAL": "Something went wrong on my side. Please try again.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Markdown constructs, stripped in order.
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})(\S.*?\S|\S)\1", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_HR_RE = re.compile(r"^\s{0,3}([-*_]\s*){3,}$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.*\S)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.MULTILINE)

# "Rs.4,850" / "Rs 4850" / "INR 4,850" / "₹4,850" -> "4,850 rupees".
# The number is captured verbatim; only the symbol placement changes.
_CURRENCY_RE = re.compile(
    r"(?:₹|\bRs\.?|\bINR\b)\s*(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_SPACE_RE = re.compile(r"[ \t]+")
_BLANKLINE_RE = re.compile(r"\n{2,}")


def strip_markdown(text: str) -> str:
    """Remove markdown syntax while keeping the words and numbers."""
    if not text:
        return ""
    out = _CODE_FENCE_RE.sub(" ", text)
    out = _INLINE_CODE_RE.sub(r"\1", out)
    out = _LINK_RE.sub(r"\1", out)
    out = _HR_RE.sub("", out)
    out = _HEADING_RE.sub("", out)
    out = _BLOCKQUOTE_RE.sub("", out)
    # Applied twice so nested emphasis (**_x_**) fully unwraps.
    out = _BOLD_ITALIC_RE.sub(r"\2", out)
    out = _BOLD_ITALIC_RE.sub(r"\2", out)
    return out


def _join_clauses(items: list[str]) -> str:
    """Join fragments the way a person would say them."""
    items = [i.rstrip(" .;,") for i in items if i.strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def flatten_tables(text: str) -> str:
    """Collapse markdown tables into spoken clauses.

    A row "| Amazon | 8000 |" becomes "Amazon: 8000", and the rows are then
    joined into one sentence. Reading pipes and dashes aloud is unusable.
    """
    if "|" not in text:
        return text
    text = _TABLE_SEP_RE.sub("", text)

    rows: list[str] = []

    def _capture(match: re.Match[str]) -> str:
        cells = [c.strip() for c in match.group(1).split("|") if c.strip()]
        if cells:
            rows.append(": ".join(cells) if len(cells) <= 2 else ", ".join(cells))
        return "\x00ROW\x00"

    text = _TABLE_ROW_RE.sub(_capture, text)
    if not rows:
        return text.replace("\x00ROW\x00", "")

    # The first row is usually a header; drop it when it carries no digits.
    if len(rows) > 1 and not any(ch.isdigit() for ch in rows[0]):
        rows = rows[1:]

    spoken = _join_clauses(rows)
    text = text.replace("\x00ROW\x00", "", 0)
    parts = [p for p in text.split("\x00ROW\x00") if p.strip()]
    text = " ".join(parts)
    return f"{text.strip()} {spoken}.".strip() if text.strip() else f"{spoken}."


def flatten_lists(text: str) -> str:
    """Turn bullet/numbered lists into a single spoken sentence."""
    bullets = _BULLET_RE.findall(text)
    if not bullets:
        return text
    remainder = _BULLET_RE.sub("\x00ITEM\x00", text)
    lead = remainder.split("\x00ITEM\x00")[0].strip()
    spoken = _join_clauses(bullets)
    if lead:
        # "Savings suggestions:" -> "Savings suggestions: a, b, and c."
        return f"{lead.rstrip(':').strip()}: {spoken}."
    return f"{spoken}."


def speakable_numbers(text: str) -> str:
    """Move currency symbols after the amount and expand "%".

    gTTS reads "Rs.4,850" as letters and "%" as "percent sign" in some voices;
    "4,850 rupees" and "16 percent" are unambiguous. Digits are untouched.
    """
    out = _CURRENCY_RE.sub(lambda m: f"{m.group(1)} rupees", text)
    return _PERCENT_RE.sub(r"\1 percent", out)


def limit_sentences(text: str, max_sentences: int) -> str:
    """Keep the first `max_sentences` sentences.

    Voice answers should be 1-3 sentences for simple questions; a chat answer
    that runs six sentences is tiring to listen to and usually front-loads the
    actual figure anyway.
    """
    if max_sentences <= 0:
        return text
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if len(sentences) <= max_sentences:
        return text.strip()
    return " ".join(sentences[:max_sentences]).strip()


def for_speech(text: str, *, max_sentences: int = 4) -> str:
    """Full written-to-spoken pipeline.

    Order matters: tables and lists are flattened while their markdown markers
    are still present, then emphasis is stripped, then numbers are made
    pronounceable, and only then is length capped.
    """
    if not text or not text.strip():
        return ""
    out = flatten_tables(text)
    out = flatten_lists(out)
    out = strip_markdown(out)
    out = speakable_numbers(out)
    out = out.replace("\n", " ")
    out = _BLANKLINE_RE.sub(" ", out)
    out = _SPACE_RE.sub(" ", out).strip()
    return limit_sentences(out, max_sentences)


#: Where a streamed answer can be cut for speech. Sentence-ending punctuation
#: must be followed by whitespace, so "45,560.75" and "1.5" are never split
#: mid-number. A newline is also a boundary, because the copilot emits bullet
#: lines that carry no terminal punctuation at all.
_STREAM_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class SentenceStreamer:
    """Turn a token stream into speech-ready sentences, one at a time.

    Streaming speech needs whole sentences. Handing a synthesiser a half-finished
    clause gives it the wrong intonation and makes it pause in the middle of a
    figure; handing it individual tokens produces stuttering. So deltas are
    buffered until a boundary is reached, and the completed sentence is then run
    through the same written-to-spoken pipeline a non-streamed answer gets.

    The spoken length cap is enforced here rather than by the caller: the on-screen
    text should stay complete even once the assistant has stopped reading aloud.
    """

    def __init__(self, *, max_sentences: int = 4) -> None:
        self._buffer = ""
        self._spoken = 0
        self._max_sentences = max_sentences

    @property
    def budget_left(self) -> bool:
        return self._max_sentences <= 0 or self._spoken < self._max_sentences

    def _prepare(self, chunk: str) -> str:
        # max_sentences=0 disables capping: the cap is applied across the whole
        # stream by _spoken, not per chunk.
        return for_speech(chunk, max_sentences=0)

    def feed(self, delta: str) -> list[str]:
        """Add streamed text, returning any sentences now ready to speak."""
        if not delta:
            return []
        self._buffer += delta
        ready: list[str] = []
        while True:
            match = _STREAM_BOUNDARY_RE.search(self._buffer)
            if not match:
                break
            head = self._buffer[: match.start()]
            self._buffer = self._buffer[match.end() :]
            if not self.budget_left:
                continue
            spoken = self._prepare(head)
            if spoken:
                ready.append(spoken)
                self._spoken += 1
        return ready

    def flush(self) -> list[str]:
        """Release whatever is left once the stream ends."""
        tail, self._buffer = self._buffer, ""
        if not tail.strip() or not self.budget_left:
            return []
        spoken = self._prepare(tail)
        if not spoken:
            return []
        self._spoken += 1
        return [spoken]


def acknowledgement(rng: random.Random | None = None) -> str:
    """A short, varied "I'm listening" line."""
    return (rng or random).choice(ACKNOWLEDGEMENTS)


def error_speech(code: str) -> str:
    """Voice-facing message for a structured error code."""
    return ERROR_SPEECH.get(code, ERROR_SPEECH["INTERNAL"])
