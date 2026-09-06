"""Auth tests: password hashing, token forgery resistance, rate limiting, accounts.

The forgery cases are the important ones — a token whose subject can be swapped
would hand any account to any caller.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time

import pytest

from auth import ratelimit, security, tokens
from db import database

PW = "correct horse battery staple"


# ---------- Password hashing ----------
def test_hashes_are_salted_and_opaque():
    a, b = security.hash_password(PW), security.hash_password(PW)
    assert a != b, "identical hashes mean the salt is not random"
    assert PW not in a
    assert a.startswith(f"{security.ALGORITHM}${security.DEFAULT_ITERATIONS}$")


def test_verify_accepts_only_the_right_password():
    stored = security.hash_password(PW)
    assert security.verify_password(PW, stored)
    assert not security.verify_password(PW + "x", stored)
    assert not security.verify_password(PW.upper(), stored)
    assert not security.verify_password("", stored)


@pytest.mark.parametrize(
    "bad", ["", "garbage", "a$b$c$d", "bcrypt$1$x$y", "pbkdf2_sha256$nope$a$b", None]
)
def test_malformed_hashes_are_rejected_not_raised(bad):
    assert security.verify_password(PW, bad) is False


def test_needs_rehash_detects_weaker_cost():
    weak = security.hash_password(PW, iterations=1000)
    assert security.verify_password(PW, weak)
    assert security.needs_rehash(weak)
    assert not security.needs_rehash(security.hash_password(PW))
    assert security.needs_rehash("garbage")


@pytest.mark.parametrize(
    "password,ok",
    [("short", False), ("12345678", True), ("        ", False), ("x" * 2000, False)],
)
def test_password_strength(password, ok):
    assert (security.validate_password_strength(password) is None) is ok


# ---------- Tokens ----------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_token_round_trip():
    token, expires_at = tokens.create_access_token("u_alice", email="a@b.com")
    payload = tokens.decode_access_token(token)
    assert payload["sub"] == "u_alice"
    assert payload["email"] == "a@b.com"
    assert expires_at > time.time()


def test_tokens_are_unique_per_issue():
    a, _ = tokens.create_access_token("u_alice")
    b, _ = tokens.create_access_token("u_alice")
    assert a != b


def test_swapping_the_subject_is_rejected():
    """The attack this design exists to stop."""
    token, _ = tokens.create_access_token("u_alice")
    body, signature = token.split(".")
    forged = json.loads(_b64d(body))
    forged["sub"] = "u_bob"
    tampered = f"{_b64e(json.dumps(forged).encode())}.{signature}"
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(tampered)


@pytest.mark.parametrize(
    "mangle",
    [
        lambda body, sig: f"{body}.{'A' * len(sig)}",  # forged signature
        lambda body, sig: f"{body}.",                   # empty signature
        lambda body, sig: body,                         # no signature
        lambda body, sig: f"{body}.{sig}.extra",        # extra segment
        lambda body, sig: "",                           # empty
        lambda body, sig: "not-a-token",                # junk
    ],
)
def test_malformed_tokens_are_rejected(mangle):
    token, _ = tokens.create_access_token("u_alice")
    body, signature = token.split(".")
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(mangle(body, signature))


def test_expired_token_is_rejected_despite_valid_signature():
    token, _ = tokens.create_access_token("u_alice", ttl_seconds=-10)
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(token)


def test_alg_none_is_rejected_even_when_signed_by_us():
    payload = {"sub": "u_bob", "exp": int(time.time()) + 999, "alg": "none"}
    body = _b64e(json.dumps(payload).encode())
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(f"{body}.{tokens._sign(body)}")


def test_subjectless_token_is_rejected():
    payload = {"sub": "", "exp": int(time.time()) + 999, "alg": "HS256"}
    body = _b64e(json.dumps(payload).encode())
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(f"{body}.{tokens._sign(body)}")


def test_token_signed_with_another_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(tokens, "_SECRET", b"a-different-secret-entirely-for-testing")
    foreign, _ = tokens.create_access_token("u_bob")
    monkeypatch.undo()
    with pytest.raises(tokens.TokenError):
        tokens.decode_access_token(foreign)


# ---------- Rate limiting ----------
def test_limiter_blocks_after_the_limit_and_isolates_keys():
    limiter = ratelimit.RateLimiter(max_attempts=3, window_seconds=60)
    key = "login:1.2.3.4:a@b.com"
    for _ in range(3):
        assert limiter.check(key) == 0
        limiter.record_failure(key)
    assert limiter.check(key) > 0
    assert limiter.check("login:1.2.3.4:other@b.com") == 0
    limiter.reset(key)
    assert limiter.check(key) == 0


def test_limiter_window_expires():
    limiter = ratelimit.RateLimiter(max_attempts=1, window_seconds=1)
    limiter.record_failure("k")
    assert limiter.check("k") > 0
    time.sleep(1.1)
    assert limiter.check("k") == 0


# ---------- Accounts ----------
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "auth.db"))
    database.init_db()
    return database


def test_password_hash_is_never_returned_by_default(fresh_db):
    created = fresh_db.create_user("u_a", "a@example.com", security.hash_password(PW))
    assert "password_hash" not in created
    assert "password_hash" not in fresh_db.get_user_by_user_id("u_a")
    assert "password_hash" not in fresh_db.get_user_by_email("a@example.com")
    assert "password_hash" in fresh_db.get_user_by_email("a@example.com", with_password=True)


@pytest.mark.parametrize(
    "user_id,email", [("u_other", "a@example.com"), ("u_a", "other@example.com")]
)
def test_duplicate_identity_is_refused(fresh_db, user_id, email):
    fresh_db.create_user("u_a", "a@example.com", security.hash_password(PW))
    with pytest.raises(fresh_db.EmailAlreadyRegistered):
        fresh_db.create_user(user_id, email, "x")


def test_password_change_invalidates_the_old_password(fresh_db):
    fresh_db.create_user("u_a", "a@example.com", security.hash_password(PW))
    fresh_db.update_password_hash("u_a", security.hash_password("a whole new password"))
    stored = fresh_db.get_user_by_email("a@example.com", with_password=True)["password_hash"]
    assert security.verify_password("a whole new password", stored)
    assert not security.verify_password(PW, stored)


def test_deleting_an_account_removes_its_data_and_spares_others(fresh_db):
    fresh_db.create_user("u_a", "a@example.com", security.hash_password(PW))
    fresh_db.create_user("u_b", "b@example.com", security.hash_password(PW))
    for uid in ("u_a", "u_b"):
        fresh_db.save_result(uid, {"health_score": {"score": 70}})
        fresh_db.save_message(uid, "user", "hi")
        fresh_db.save_simulation(uid, "s", {}, {})
        fresh_db.upsert_memory(uid, "goal", "g1", "buy a car")
        fresh_db.save_goal(uid, "Car", "car", 100.0)

    assert fresh_db.delete_user("u_a")
    assert fresh_db.get_user_by_user_id("u_a") is None
    assert fresh_db.get_result("u_a") is None
    assert fresh_db.get_conversation("u_a") == []
    assert fresh_db.list_simulations("u_a") == []
    assert fresh_db.get_memories("u_a") == []
    assert fresh_db.list_goals("u_a") == []

    # The other account is untouched.
    assert fresh_db.get_result("u_b") is not None
    assert len(fresh_db.list_goals("u_b")) == 1
    assert not fresh_db.delete_user("u_ghost")


def test_migration_adds_users_to_a_pre_auth_database(tmp_path, monkeypatch):
    """A database from before auth existed must gain the table, keeping its data."""
    path = str(tmp_path / "legacy.db")
    monkeypatch.setattr(database, "_DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE results (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO results VALUES ('demo_user','{\"health_score\":{\"score\":42}}',"
            "'2026-01-01')"
        )

    database.init_db()
    assert database.get_result("demo_user") is not None
    assert database.count_users() == 0
    database.create_user("u_new", "new@example.com", security.hash_password(PW))
    assert database.count_users() == 1
    database.init_db()  # idempotent


def test_db_path_is_configurable(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "custom.db"
    monkeypatch.setenv("CFO_DB_PATH", str(target))
    assert database._resolve_db_path() == str(target)

    monkeypatch.delenv("CFO_DB_PATH")
    monkeypatch.setenv("CFO_DATA_DIR", str(tmp_path))
    assert database._resolve_db_path() == str(tmp_path / "cfo.db")

    monkeypatch.delenv("CFO_DATA_DIR")
    assert database._resolve_db_path().endswith("cfo.db")


def test_nested_db_directory_is_created(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "deep" / "deeper" / "x.db"))
    database.init_db()
    assert (tmp_path / "deep" / "deeper" / "x.db").is_file()
