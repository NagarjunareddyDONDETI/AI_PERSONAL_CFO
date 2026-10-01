"""The daemon's only door into Finzo's intelligence.

It calls ``main.voice_ask`` in-process, the exact coroutine behind POST
/voice/ask. So a question spoken to the daemon goes through the same follow-up
resolution, retrieval, memory, intent routing, data slicing and
``copilot.converse`` grounding as a question typed into the dashboard. No
financial logic is re-implemented here, and every figure in the answer comes from
the computed results stored for the user.

In-process rather than over HTTP means the daemon needs no bearer token and keeps
working when the API server is not running at all.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("voice.handsfree.bridge")


class BridgeError(RuntimeError):
    """The daemon cannot answer for anyone (no user, no database)."""


class CFOBridge:
    def __init__(self, *, user_email: str = "") -> None:
        self._user_email = user_email
        self._main = None
        self.user_id: str | None = None
        self.has_data = False

    def connect(self) -> None:
        """Import the app and resolve which account the daemon answers for."""
        import main  # heavy: loads the DB, RAG and LLM router exactly once

        from auth.deps import normalize_email
        from db import database

        self._main = main
        if self._user_email:
            user = database.get_user_by_email(normalize_email(self._user_email))
            if not user:
                raise BridgeError(
                    "FINZO_VOICE_USER_EMAIL does not match any account. "
                    "Use the email you sign in to the dashboard with."
                )
        else:
            with database._connect() as conn:  # noqa: SLF001
                rows = conn.execute("SELECT user_id FROM users LIMIT 2").fetchall()
            if len(rows) != 1:
                raise BridgeError(
                    "Set FINZO_VOICE_USER_EMAIL in backend/.env to choose whose "
                    f"finances Finzo answers about ({len(rows)}+ accounts exist)."
                )
            user = database.get_user_by_user_id(rows[0]["user_id"])
        self.user_id = user["user_id"]
        self.has_data = database.get_result(self.user_id) is not None
        if not self.has_data:
            logger.warning("this account has no analysed statement yet; answers will say so")

    def keep_alive(self) -> None:
        """Mark the conversation as active right now.

        Called when Finzo finishes speaking. The session's idle timeout starts
        from its last activity, which was when the answer was *generated*; a 20
        second spoken answer used to consume most of the 30 second window, so
        "what about last month?" arrived after the context had been wiped.
        """
        if self._main is None or self.user_id is None:
            return
        session = self._main.voice_conversation.registry.peek(self.user_id)
        if session is not None:
            session.touch()

    def ask(self, text: str) -> dict:
        """Answer one question. Returns the /voice/ask payload. Never raises."""
        if self._main is None or self.user_id is None:
            raise BridgeError("bridge not connected")
        from fastapi import BackgroundTasks

        main = self._main
        background = BackgroundTasks()

        async def _run() -> dict:
            result = await main.voice_ask(
                user_id=self.user_id,
                background=background,
                file=None,
                speak=False,  # the daemon speaks locally
                timeout_seconds=main.voice_conversation.DEFAULT_TIMEOUT_SECONDS,
                client_transcript=text,
            )
            await background()  # memory summarisation, as the server would run it
            return result

        try:
            return asyncio.run(_run())
        except Exception:  # noqa: BLE001
            logger.exception("CFO pipeline failed")
            return {
                "ok": False,
                "action": "answer",
                "speech": "I'm having trouble reaching your financial data right now.",
                "response": "",
                "error": {"code": "INTERNAL"},
            }
