"""SQLite persistence for accounts, transactions, scores, and processed results.

Stores the full processed result blob per user as JSON so the dashboard,
chat, and what-if endpoints can read a consistent snapshot without
re-running the pipeline every request.

Every per-user table keys on an opaque TEXT ``user_id`` issued by the ``users``
table, so account records and financial data stay decoupled.

Database location resolves in this order:
  1. ``CFO_DB_PATH``  — full path to the database file
  2. ``CFO_DATA_DIR`` — directory to place ``cfo.db`` in
  3. ``backend/db/cfo.db`` (default)

On a host with an ephemeral filesystem (Render, Heroku, most containers) point
one of those at a mounted persistent volume, or the data is lost on redeploy.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

_DB_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_db_path() -> str:
    explicit = (os.getenv("CFO_DB_PATH") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    data_dir = (os.getenv("CFO_DATA_DIR") or "").strip()
    if data_dir:
        return os.path.join(os.path.abspath(os.path.expanduser(data_dir)), "cfo.db")
    return os.path.join(_DB_DIR, "cfo.db")


_DB_PATH = _resolve_db_path()

# Serialises writes within this process. SQLite handles cross-process locking
# itself, but a single lock here avoids gratuitous "database is locked" retries
# when FastAPI runs sync endpoints across its thread pool.
_write_lock = threading.Lock()


def db_path() -> str:
    """The database file currently in use (useful for diagnostics)."""
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    # Read _DB_PATH at call time so tests can point it at a temp file.
    parent = os.path.dirname(_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    # WAL lets readers proceed during a write, which matters because the
    # dashboard fans out into several queries per page load.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.DatabaseError:
        pass  # e.g. :memory: or a read-only volume — not worth failing over.
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                name TEXT,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT
            );
            CREATE TABLE IF NOT EXISTS results (
                user_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS score_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                score INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                intent TEXT,
                llm_used INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations(user_id, id);
            CREATE TABLE IF NOT EXISTS simulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                params TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_simulations_user
                ON simulations(user_id, id);
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                mem_key TEXT NOT NULL,
                content TEXT NOT NULL,
                data TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, kind, mem_key)
            );
            CREATE INDEX IF NOT EXISTS idx_memories_user
                ON memories(user_id, kind);
            CREATE TABLE IF NOT EXISTS financial_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                goal_type TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_saved REAL NOT NULL DEFAULT 0,
                target_months INTEGER,
                monthly_contribution REAL,
                annual_return REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_goals_user
                ON financial_goals(user_id, id);
            """
        )
    _migrate()


def _migrate() -> None:
    """Apply additive column migrations to databases created by older versions.

    SQLite cannot add a column conditionally, so we inspect the schema first.
    Each entry is (table, column, DDL) and is safe to re-run.
    """
    additive: list[tuple[str, str, str]] = [
        ("financial_goals", "annual_return", "REAL NOT NULL DEFAULT 0"),
        ("users", "last_login_at", "TEXT"),
        ("users", "name", "TEXT"),
    ]
    with _connect() as conn:
        for table, column, ddl in additive:
            existing = {
                r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing or column in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# ---------- Accounts ----------
# Never select password_hash unless a credential check needs it.
_PUBLIC_USER_COLS = "id, user_id, email, name, created_at, last_login_at"

# Tables holding per-user financial data, keyed on the opaque user_id.
_USER_DATA_TABLES = (
    "transactions",
    "results",
    "score_history",
    "conversations",
    "simulations",
    "memories",
    "financial_goals",
)


class EmailAlreadyRegistered(Exception):
    """Raised when an email is already present in the users table."""


def create_user(user_id: str, email: str, password_hash: str, name: str = "") -> dict:
    """Insert a new account and return its public row.

    ``email`` must already be normalised (trimmed + lowercased) by the caller.
    Raises EmailAlreadyRegistered if the address or id is taken; the UNIQUE
    constraint is what actually decides, so two concurrent signups cannot both win.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _write_lock, _connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (user_id, email, name, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, email, name or None, password_hash, now),
            )
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyRegistered(str(exc)) from exc
        row = conn.execute(
            f"SELECT {_PUBLIC_USER_COLS} FROM users WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def get_user_by_email(email: str, *, with_password: bool = False) -> dict | None:
    """Look up an account by normalised email.

    Pass ``with_password=True`` only where a credential check happens.
    """
    cols = _PUBLIC_USER_COLS + (", password_hash" if with_password else "")
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {cols} FROM users WHERE email = ?", (email,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_user_id(user_id: str) -> dict | None:
    """Look up an account by its opaque public id. Never returns the hash."""
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {_PUBLIC_USER_COLS} FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def user_id_exists(user_id: str) -> bool:
    with _connect() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            is not None
        )


def count_users() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


def touch_last_login(user_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _write_lock, _connect() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE user_id = ?", (now, user_id)
        )


def update_password_hash(user_id: str, password_hash: str) -> bool:
    """Replace a stored hash — used to transparently upgrade the KDF cost."""
    with _write_lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (password_hash, user_id),
        )
        return cur.rowcount > 0


def delete_user(user_id: str) -> bool:
    """Delete an account and every row of its financial data.

    Done in one transaction so a failure cannot leave an account deleted but its
    statements behind (or vice versa).
    """
    with _write_lock, _connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        removed = cur.rowcount > 0
        for table in _USER_DATA_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    return removed


def save_transactions(user_id: str, categorized: list[dict]) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO transactions (user_id, date, description, amount, category) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (user_id, t["date"], t["description"], t["amount"], t.get("category"))
                for t in categorized
            ],
        )


def save_result(user_id: str, payload: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO results (user_id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, "
            "updated_at=excluded.updated_at",
            (user_id, json.dumps(payload), now),
        )
        score = payload.get("health_score", {}).get("score")
        if score is not None:
            conn.execute(
                "INSERT INTO score_history (user_id, score, created_at) VALUES (?, ?, ?)",
                (user_id, int(score), now),
            )


def get_result(user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM results WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload"])


def get_transactions(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, description, amount, category FROM transactions "
            "WHERE user_id = ? ORDER BY date",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- Conversation memory (Phase 1: AI Financial Copilot) ----------
def save_message(
    user_id: str,
    role: str,
    content: str,
    intent: str | None = None,
    llm_used: bool | None = None,
) -> None:
    """Persist a single chat message (role: 'user' | 'assistant')."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, intent, llm_used, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                role,
                content,
                intent,
                None if llm_used is None else int(bool(llm_used)),
                now,
            ),
        )


def get_conversation(user_id: str, limit: int = 50) -> list[dict]:
    """Return the most recent messages for a user in chronological order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, intent, llm_used, created_at FROM conversations "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    out: list[dict] = []
    for r in reversed(rows):
        d = dict(r)
        if d.get("llm_used") is not None:
            d["llm_used"] = bool(d["llm_used"])
        out.append(d)
    return out


def clear_conversation(user_id: str) -> int:
    """Delete a user's conversation history. Returns rows removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        )
        return cur.rowcount


# ---------- Digital Financial Twin (Phase 3: saved simulations) ----------
def save_simulation(user_id: str, name: str, params: dict, result: dict) -> int:
    """Persist a simulation and return its new id."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO simulations (user_id, name, params, result, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, name, json.dumps(params), json.dumps(result), now),
        )
        return int(cur.lastrowid)


def list_simulations(user_id: str) -> list[dict]:
    """Return saved simulations (metadata + full payload) newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, params, result, created_at FROM simulations "
            "WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "params": json.loads(r["params"]),
                "result": json.loads(r["result"]),
                "created_at": r["created_at"],
            }
        )
    return out


def get_simulation(sim_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, name, params, result, created_at FROM simulations "
            "WHERE id = ?",
            (sim_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "params": json.loads(row["params"]),
        "result": json.loads(row["result"]),
        "created_at": row["created_at"],
    }


def delete_simulation(sim_id: int, user_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM simulations WHERE id = ? AND user_id = ?", (sim_id, user_id)
        )
        return cur.rowcount > 0


# ---------- Long-term memory (Phase 5) ----------
def upsert_memory(
    user_id: str, kind: str, mem_key: str, content: str, data: dict | None = None
) -> None:
    """Insert or update one memory item (unique by user_id+kind+mem_key)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memories (user_id, kind, mem_key, content, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, kind, mem_key) DO UPDATE SET "
            "content=excluded.content, data=excluded.data, updated_at=excluded.updated_at",
            (user_id, kind, mem_key, content, json.dumps(data or {}), now, now),
        )


def get_memories(user_id: str, kind: str | None = None, limit: int = 500) -> list[dict]:
    """Return a user's memories (optionally filtered by kind), newest first."""
    with _connect() as conn:
        if kind:
            rows = conn.execute(
                "SELECT kind, mem_key, content, data, created_at, updated_at FROM memories "
                "WHERE user_id = ? AND kind = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT kind, mem_key, content, data, created_at, updated_at FROM memories "
                "WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["data"] = {}
        out.append(d)
    return out


def delete_memories(user_id: str, kind: str | None = None) -> int:
    """Delete a user's memories (optionally only one kind). Returns rows removed."""
    with _connect() as conn:
        if kind:
            cur = conn.execute(
                "DELETE FROM memories WHERE user_id = ? AND kind = ?", (user_id, kind)
            )
        else:
            cur = conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        return cur.rowcount


def prune_memories(user_id: str, kinds: list[str], keep_keys: list[str]) -> int:
    """Delete auto-derived memories of the given kinds that are no longer
    present in the latest extraction.

    Used after re-processing a statement so stale facts (e.g. subscriptions from
    a previously-loaded sample) don't linger when the new data no longer has
    them. User-authored kinds (goals, preferences) are never touched.
    Returns rows removed.
    """
    if not kinds:
        return 0
    kind_ph = ",".join("?" for _ in kinds)
    params: list = [user_id, *kinds]
    sql = (
        f"DELETE FROM memories WHERE user_id = ? AND kind IN ({kind_ph})"
    )
    if keep_keys:
        key_ph = ",".join("?" for _ in keep_keys)
        sql += f" AND mem_key NOT IN ({key_ph})"
        params.extend(keep_keys)
    with _connect() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


# ---------- Financial goals (Phase 9: Goal Planner) ----------
def save_goal(
    user_id: str,
    name: str,
    goal_type: str,
    target_amount: float,
    current_saved: float = 0.0,
    target_months: int | None = None,
    monthly_contribution: float | None = None,
    annual_return: float = 0.0,
) -> int:
    """Persist a goal and return its new id."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO financial_goals "
            "(user_id, name, goal_type, target_amount, current_saved, target_months, "
            "monthly_contribution, annual_return, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, name, goal_type, float(target_amount), float(current_saved),
                target_months, monthly_contribution, float(annual_return or 0.0), now,
            ),
        )
        return int(cur.lastrowid)


def list_goals(user_id: str) -> list[dict]:
    """Return a user's goals (raw rows), newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, goal_type, target_amount, current_saved, target_months, "
            "monthly_contribution, annual_return, created_at FROM financial_goals "
            "WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_goal(goal_id: int, user_id: str) -> bool:
    """Delete a goal. Returns True if a row was removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM financial_goals WHERE id = ? AND user_id = ?", (goal_id, user_id)
        )
        return cur.rowcount > 0
