"""Keyword-based intent router (Phase 2 step 4).

Routes a chat or voice query to a coarse intent so the explainer can pull the
right slice of state. LLM handles final phrasing.

ORDERING IS SIGNIFICANT. The first intent with a matching keyword wins, so more
specific intents must be declared before broader ones. Two examples that break if
reordered:

  - "goal" precedes "savings" because "I'm saving for a car" contains "save" but
    is about a goal, not a request for savings advice.
  - "subscription" precedes "spending" because "how much do I spend on
    subscriptions" contains "how much" and "spend".

The six original labels (whatif, forecast, anomaly, score, savings, spending) are
consumed by ``agents.explainer._relevant_slice`` and asserted on in the test
suite; their keywords are unchanged. Later additions only capture queries that
previously fell through to the "spending" default.
"""
from __future__ import annotations

_INTENTS = {
    "whatif": ["what if", "what-if", "should i buy", "afford", "emi", "loan", "purchase"],
    "forecast": ["predict", "forecast", "next month", "will i", "future"],
    "anomaly": ["anomaly", "unusual", "spike", "why did", "why is", "strange"],
    "score": ["score", "health", "rating", "how am i doing"],
    # Declared before "savings": a stated goal is not a request for advice.
    "goal": [
        "goal", "goals", "saving for", "save for", "saving up", "target amount",
        "down payment", "emergency fund",
    ],
    "savings": ["save", "cut back", "reduce", "budget", "advice", "suggest"],
    # Declared before "spending": these queries also contain "spend"/"how much".
    "subscription": [
        "subscription", "subscriptions", "recurring", "netflix", "spotify",
        "prime", "hotstar", "membership",
    ],
    "transaction_search": [
        "transaction", "transactions", "find a payment", "search for",
        "show me all", "list all", "statement history", "previous statement",
    ],
    "spending": ["spend", "spent", "how much", "category", "food", "shopping"],
    # Financial literacy questions with no personal figures involved. Last,
    # because it is the broadest and would otherwise shadow everything above.
    "general_finance": [
        "50/30/20", "50 30 20", "rule of thumb", "what does it mean",
        "explain the", "what is the", "how does", "difference between",
        "should i invest", "mutual fund", "sip", "inflation",
    ],
}

#: Public list of routable intents, for docs/tests/UI.
INTENTS: tuple[str, ...] = tuple(_INTENTS) + ("unknown",)

#: Default when nothing matches. Kept as "spending" for backward compatibility:
#: the explainer's default slice (monthly summary + health score) is the most
#: broadly useful context, and callers already rely on this behaviour.
DEFAULT_INTENT = "spending"


def route_intent(query: str) -> str:
    q = query.lower()
    for intent, keywords in _INTENTS.items():
        if any(kw in q for kw in keywords):
            return intent
    return DEFAULT_INTENT
