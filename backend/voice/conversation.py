"""Voice conversation state for Finzo.

Two responsibilities:

  1. Track what the current conversation is *about* (topic, category, metric) so
     elliptical follow-ups can be rewritten into self-contained questions BEFORE
     they reach the LLM. The requirement is explicit that follow-up resolution
     must not depend solely on the model, and there is a practical reason: the
     copilot prompt is told never to invent numbers, so an under-specified
     question like "why?" tends to produce a hedge rather than an answer. Handing
     it "Why was my Food spending high last month?" gets a real answer.

  2. Keep a per-user session with a turn log for observability.

Storage is in-process and intentionally NOT the database: these are transient
dialogue mechanics, and the durable record already exists via
``database.save_message`` (chat history) and ``agents.memory`` (long-term
memory). Raw audio is never held here -- only transcribed text.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from .wake import normalize

logger = logging.getLogger("voice.conversation")

#: Seconds of silence before conversation mode drops back to wake-word mode.
DEFAULT_TIMEOUT_SECONDS = 30
#: 0 means "never time out" (the UI's "Never" option).
NEVER_TIMEOUT = 0
ALLOWED_TIMEOUTS = (10, 30, 60, NEVER_TIMEOUT)

#: Cap on retained turns per session, so a long hands-free session cannot grow
#: without bound in memory.
MAX_TURNS = 40

#: Idle sessions are dropped after this long to stop the registry leaking.
SESSION_TTL_SECONDS = 3600

# Canonical categories produced by agents.categorization, mapped from the words
# people actually say. Keys are matched as whole words against the utterance.
_CATEGORY_SYNONYMS: dict[str, str] = {
    "food": "Food", "groceries": "Food", "grocery": "Food", "eating": "Food",
    "dining": "Food", "restaurants": "Food", "restaurant": "Food",
    "swiggy": "Food", "zomato": "Food",
    "shopping": "Shopping", "amazon": "Shopping", "clothes": "Shopping",
    "flipkart": "Shopping", "myntra": "Shopping",
    "entertainment": "Entertainment", "netflix": "Entertainment",
    "movies": "Entertainment", "hotstar": "Entertainment", "prime": "Entertainment",
    "travel": "Travel", "uber": "Travel", "ola": "Travel", "flights": "Travel",
    "flight": "Travel", "trips": "Travel", "trip": "Travel",
    "housing": "Housing", "rent": "Housing",
    "utilities": "Utilities", "electricity": "Utilities", "bills": "Utilities",
    "bill": "Utilities", "phone": "Utilities", "internet": "Utilities",
    "income": "Income", "salary": "Income",
}

# The thing being asked about, independent of category.
_METRIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("health_score", ("health score", "score", "rating")),
    ("forecast", ("forecast", "next month", "predict", "will i spend")),
    ("savings", ("save", "saving", "savings", "reduce", "cut back")),
    ("anomaly", ("anomaly", "unusual", "spike", "strange")),
    ("subscriptions", ("subscription", "subscriptions", "recurring")),
    ("spending", ("spend", "spent", "spending", "expense", "expenses", "cost")),
)

# Utterances that only make sense against prior context.
_WHY_MARKERS = ("why", "how come", "what caused", "what's causing", "whats causing")
_SWITCH_MARKERS = ("what about", "how about", "and what about", "what of", "and")
_PRONOUN_MARKERS = ("that", "it", "this", "those", "them")

_WORD_RE = re.compile(r"[a-z]+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(normalize(text))


def detect_category(text: str) -> str | None:
    """Map spoken words onto a canonical category label, or None."""
    for word in _words(text):
        if word in _CATEGORY_SYNONYMS:
            return _CATEGORY_SYNONYMS[word]
    return None


def detect_metric(text: str) -> str | None:
    """Identify what is being asked about (spending, forecast, score, ...)."""
    normalized = normalize(text)
    for metric, needles in _METRIC_PATTERNS:
        if any(n in normalized for n in needles):
            return metric
    return None


@dataclass
class VoiceTurn:
    """One exchange. Deliberately holds text only -- never audio."""

    timestamp: float
    text: str
    resolved_text: str
    intent: str
    response: str
    duration_ms: int
    status: str  # "ok" | "error" | "interrupted"

    def snapshot(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "text": self.text,
            "resolved_text": self.resolved_text,
            "intent": self.intent,
            "response": self.response,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }


@dataclass
class VoiceSession:
    """Per-user hands-free dialogue state."""

    user_id: str
    voice_session_id: str
    conversation_id: str
    created_at: float
    last_activity_at: float
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    current_topic: str | None = None
    last_intent: str | None = None
    last_category: str | None = None
    last_metric: str | None = None
    last_entities: dict = field(default_factory=dict)
    last_response: str | None = None
    turns: list[VoiceTurn] = field(default_factory=list)

    # ---- lifecycle -------------------------------------------------------- #
    def touch(self, now: float | None = None) -> None:
        self.last_activity_at = now if now is not None else time.time()

    def is_expired(self, now: float | None = None) -> bool:
        """True when conversation mode should fall back to wake-word mode."""
        if self.timeout_seconds == NEVER_TIMEOUT:
            return False
        now = now if now is not None else time.time()
        return (now - self.last_activity_at) > self.timeout_seconds

    def reset_context(self) -> None:
        """Forget dialogue context but keep the session identity and log."""
        self.current_topic = None
        self.last_intent = None
        self.last_category = None
        self.last_metric = None
        self.last_entities = {}
        self.last_response = None

    # ---- follow-up resolution -------------------------------------------- #
    def resolve(self, text: str) -> str:
        """Rewrite an elliptical follow-up into a self-contained question.

        Returns the original text unchanged when it already stands alone, so
        this is safe to run on every utterance.
        """
        normalized = normalize(text)
        if not normalized:
            return normalized

        words = normalized.split(" ")
        spoken_category = detect_category(normalized)
        spoken_metric = detect_metric(normalized)

        # "What about shopping?" -- new category, carry the previous metric.
        if spoken_category and not spoken_metric:
            if any(normalized.startswith(m + " ") for m in _SWITCH_MARKERS):
                metric = self.last_metric or "spending"
                return self._phrase(metric, spoken_category)

        # "Why?" / "Why is that high?" -- carry both metric and category.
        if any(normalized == m or normalized.startswith(m + " ") for m in _WHY_MARKERS):
            if self.last_category or self.last_metric:
                subject = self._phrase(
                    self.last_metric or "spending",
                    spoken_category or self.last_category,
                )
                # Preserve any qualifier the user added ("why is that HIGH").
                qualifier = " ".join(w for w in words if w in ("high", "low", "up", "down"))
                tail = f" Specifically, why is it {qualifier}?" if qualifier else ""
                return f"{subject} Explain why.{tail}".strip()

        # "Can I reduce that?" / "is it high?" -- pronoun with no new subject.
        if not spoken_category and any(w in _PRONOUN_MARKERS for w in words):
            if self.last_category or self.last_metric:
                subject = self._phrase(self.last_metric or "spending", self.last_category)
                # Keep the user's verb so intent routing still sees "reduce".
                return f"{normalized} (referring to: {subject})"

        return normalized

    def _phrase(self, metric: str, category: str | None) -> str:
        """Build an explicit question for a metric/category pair."""
        if metric == "health_score":
            return "What is my financial health score?"
        if metric == "forecast":
            target = f" on {category}" if category else ""
            return f"What is my forecast expense for next month{target}?"
        if metric == "savings":
            target = f" on {category}" if category else ""
            return f"How can I save more{target}?"
        if metric == "anomaly":
            target = f" in {category}" if category else ""
            return f"What unusual spending was detected{target}?"
        if metric == "subscriptions":
            return "What subscriptions do I have?"
        target = f" on {category}" if category else ""
        return f"How much did I spend{target}?"

    # ---- recording -------------------------------------------------------- #
    def note_turn(
        self,
        *,
        text: str,
        resolved_text: str,
        intent: str,
        response: str,
        duration_ms: int,
        status: str = "ok",
    ) -> VoiceTurn:
        """Record a completed exchange and update dialogue context."""
        turn = VoiceTurn(
            timestamp=time.time(),
            text=text,
            resolved_text=resolved_text,
            intent=intent,
            response=response,
            duration_ms=duration_ms,
            status=status,
        )
        self.turns.append(turn)
        if len(self.turns) > MAX_TURNS:
            del self.turns[: len(self.turns) - MAX_TURNS]

        if status == "ok":
            # Context comes from the resolved text: after "what about shopping?"
            # the topic is Shopping, which only the rewritten form states.
            category = detect_category(resolved_text) or detect_category(text)
            metric = detect_metric(resolved_text) or detect_metric(text)
            if category:
                self.last_category = category
            if metric:
                self.last_metric = metric
            self.last_intent = intent
            self.last_response = response
            self.current_topic = category or metric or self.current_topic
            self.last_entities = {
                k: v for k, v in {"category": category, "metric": metric}.items() if v
            }
        self.touch()
        return turn

    def snapshot(self) -> dict:
        return {
            "voice_session_id": self.voice_session_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "timeout_seconds": self.timeout_seconds,
            "current_topic": self.current_topic,
            "last_intent": self.last_intent,
            "last_category": self.last_category,
            "last_metric": self.last_metric,
            "last_entities": dict(self.last_entities),
            "turns": [t.snapshot() for t in self.turns],
        }


class SessionRegistry:
    """Thread-safe per-user session store.

    FastAPI runs sync endpoints across a thread pool, so concurrent voice turns
    for the same user are possible; the lock keeps session mutation atomic.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, VoiceSession] = {}

    def get_or_create(
        self, user_id: str, *, timeout_seconds: int | None = None
    ) -> VoiceSession:
        now = time.time()
        with self._lock:
            self._evict_stale(now)
            session = self._sessions.get(user_id)
            if session is None or session.is_expired(now):
                if session is not None:
                    logger.info(
                        "voice session expired user=%s id=%s turns=%d",
                        user_id, session.voice_session_id, len(session.turns),
                    )
                session = VoiceSession(
                    user_id=user_id,
                    voice_session_id=f"vs_{secrets.token_urlsafe(9)}",
                    conversation_id=f"vc_{secrets.token_urlsafe(9)}",
                    created_at=now,
                    last_activity_at=now,
                    timeout_seconds=(
                        timeout_seconds
                        if timeout_seconds is not None
                        else DEFAULT_TIMEOUT_SECONDS
                    ),
                )
                self._sessions[user_id] = session
            elif timeout_seconds is not None:
                session.timeout_seconds = timeout_seconds
            return session

    def peek(self, user_id: str) -> VoiceSession | None:
        with self._lock:
            return self._sessions.get(user_id)

    def end(self, user_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(user_id, None) is not None

    def _evict_stale(self, now: float) -> None:
        stale = [
            uid for uid, s in self._sessions.items()
            if (now - s.last_activity_at) > SESSION_TTL_SECONDS
        ]
        for uid in stale:
            del self._sessions[uid]


#: App-wide registry, mirroring how ``voice.service`` exposes its singleton.
registry = SessionRegistry()
