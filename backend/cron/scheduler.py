"""Autonomous Background Scheduler for AI Personal CFO.

Periodically executes financial health sentinels, anomaly monitors,
and executive reports for active users.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from cron import monitors
from db import database

logger = logging.getLogger("cron.scheduler")


class AutonomousFinancialScheduler:
    """Lightweight background thread scheduler for periodic CFO monitors."""

    def __init__(self, interval_seconds: int = 3600) -> None:
        self.interval_seconds = interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="cfo-cron-scheduler")
            self._thread.start()
            logger.info("Autonomous Financial Scheduler started (interval=%ds)", self.interval_seconds)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            logger.info("Autonomous Financial Scheduler stopping")

    def _run_loop(self) -> None:
        while self._running:
            try:
                self.run_scheduled_monitors_for_all_users()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in autonomous financial scheduler cycle: %s", exc, exc_info=True)

            # Sleep in short increments to allow rapid clean shutdown
            for _ in range(max(1, self.interval_seconds // 5)):
                if not self._running:
                    break
                time.sleep(5)

    def run_scheduled_monitors_for_all_users(self) -> dict[str, Any]:
        """Iterate over all active user accounts and run monitors."""
        with database._connect() as conn:
            rows = conn.execute("SELECT user_id FROM results").fetchall()
            user_ids = [r["user_id"] for r in rows]

        results = {}
        for uid in user_ids:
            try:
                daily = monitors.run_daily_anomaly_monitor(uid)
                weekly = monitors.run_weekly_budget_pulse(uid)
                results[uid] = {"daily_anomaly": daily, "weekly_pulse": weekly}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed running monitors for user=%s: %s", uid, exc)

        return {"users_processed": len(user_ids), "details": results}


# Singleton scheduler instance
scheduler = AutonomousFinancialScheduler()
