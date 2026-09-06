"""API-level auth tests against the real FastAPI app.

These are the regression tests for the vulnerability this feature closed: before
auth, every endpoint took a `user_id` from the caller, so anyone could read or
delete anyone's financial data. `test_cross_user_*` are the ones that matter.
"""
from __future__ import annotations

import itertools
import os

import pytest

# The token secret is read when auth.tokens is imported, so set it before that.
os.environ.setdefault("AUTH_SECRET", "test-secret-long-enough-for-the-length-check-0123")

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from db import database  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """A TestClient backed by a throwaway database.

    ``_DB_PATH`` is patched on the module object rather than via CFO_DB_PATH:
    ``db.database`` is already imported by the time fixtures run, and
    ``_resolve_db_path()`` only reads the environment at import time. Patching
    the attribute works because ``_connect()`` re-reads it on every call — get
    this wrong and the suite writes into the real backend/db/cfo.db.
    """
    original = database._DB_PATH
    database._DB_PATH = str(tmp_path_factory.mktemp("api") / "api.db")
    import main

    assert database._DB_PATH != original, "test database path was not applied"
    with fastapi_testclient.TestClient(main.app) as c:
        c.app_module = main  # type: ignore[attr-defined]
        yield c
    database._DB_PATH = original


@pytest.fixture(autouse=True)
def _reset_limiters(client):
    """Registration is capped at 5/hour per IP, which this suite would trip."""
    main = client.app_module  # type: ignore[attr-defined]
    main.auth.register_limiter.clear()
    main.auth.login_limiter.clear()
    yield
    main.auth.register_limiter.clear()
    main.auth.login_limiter.clear()


_counter = itertools.count()


def _email(label: str) -> str:
    """Unique per call, so tests never collide through shared database state."""
    return f"{label}-{next(_counter)}@example.com"


def _register(client, email: str, password: str = "a good long password") -> dict:
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return res.json()


def _auth(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


PUBLIC = ["/health", "/capabilities", "/goals/types", "/explain/subjects", "/workflow/graph"]

PROTECTED = [
    ("get", "/dashboard"), ("get", "/forecast"), ("get", "/health-score"),
    ("get", "/chat/history"), ("delete", "/chat/history"), ("get", "/goals"),
    ("get", "/memory"), ("delete", "/memory"), ("get", "/twin/scenarios"),
    ("get", "/workflow/trace"), ("get", "/auth/me"), ("delete", "/auth/me"),
    ("get", "/metrics/llm"), ("get", "/router/status"), ("get", "/voice/metrics"),
    ("post", "/chat"), ("post", "/debate"), ("post", "/explain"),
    ("post", "/rag/trace"), ("post", "/goals"), ("post", "/whatif"),
    ("post", "/twin/simulate"), ("post", "/twin/compare"), ("post", "/llm/chat"),
    ("post", "/router/provider"), ("post", "/memory/preference"),
    ("post", "/memory/goal"), ("post", "/voice/speak"), ("post", "/upload"),
    ("post", "/load-sample"), ("delete", "/goals/1"), ("delete", "/twin/scenario/1"),
]


@pytest.mark.parametrize("path", PUBLIC)
def test_public_endpoints_need_no_token(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_endpoints_reject_anonymous_callers(client, method, path):
    res = client.post(path, json={}) if method == "post" else getattr(client, method)(path)
    assert res.status_code == 401, f"{method.upper()} {path} was reachable without a token"


@pytest.mark.parametrize(
    "header", ["Bearer nonsense", "Bearer ", "Basic abc", "nonsense", ""]
)
def test_bad_authorization_headers_are_rejected(client, header):
    assert client.get("/dashboard", headers={"Authorization": header}).status_code == 401


def test_capabilities_advertises_that_auth_is_required(client):
    assert client.get("/capabilities").json()["auth_required"] is True


# ---------- Registration and login ----------
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"email": "not-an-email", "password": "long enough password"}, 422),
        ({"email": "ok@example.com", "password": "short"}, 422),
    ],
)
def test_registration_validation(client, payload, status):
    assert client.post("/auth/register", json=payload).status_code == status


def test_registration_normalises_email_and_hides_secrets(client):
    email = _email("MiXeD")
    res = client.post(
        "/auth/register",
        json={"email": f"  {email.upper()} ", "password": "a good long password"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["user"]["email"] == email.lower()
    assert res.json()["user"]["user_id"].startswith("u_")
    assert "password" not in res.text


def test_duplicate_email_conflicts(client):
    email = _email("dupe")
    _register(client, email)
    res = client.post(
        "/auth/register", json={"email": email, "password": "another password"}
    )
    assert res.status_code == 409


def test_login_does_not_reveal_whether_an_email_exists(client):
    """Identical responses, so login cannot be used to harvest addresses."""
    known = _email("known")
    _register(client, known)
    wrong = client.post("/auth/login", json={"email": known, "password": "wrong password"})
    unknown = client.post(
        "/auth/login", json={"email": _email("absent"), "password": "wrong password"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_returns_a_working_token(client):
    email = _email("worker")
    _register(client, email)
    res = client.post(
        "/auth/login", json={"email": email, "password": "a good long password"}
    )
    assert res.status_code == 200
    me = client.get("/auth/me", headers=_auth(res.json()))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email
    assert me.json()["user"]["last_login_at"]


# ---------- The isolation guarantees ----------
def test_cross_user_read_is_blocked(client):
    alice = _register(client, _email("alice-read"))
    bob = _register(client, _email("bob-read"))

    loaded = client.post(
        "/load-sample", data={"name": "sample_1.csv"}, headers=_auth(alice)
    )
    assert loaded.status_code == 200, loaded.text
    assert client.get("/dashboard", headers=_auth(alice)).status_code == 200

    # Bob uploaded nothing, so he must see nothing — not Alice's statement.
    assert client.get("/dashboard", headers=_auth(bob)).status_code == 404
    assert client.get("/goals", headers=_auth(bob)).json()["goals"] == []
    assert client.get("/chat/history", headers=_auth(bob)).json()["history"] == []


def test_cross_user_delete_is_blocked(client):
    alice = _register(client, _email("alice-del"))
    bob = _register(client, _email("bob-del"))

    created = client.post(
        "/goals",
        headers=_auth(alice),
        json={"name": "Car", "goal_type": "car", "target_amount": 500000, "target_months": 24},
    )
    assert created.status_code == 200, created.text
    goal_id = created.json()["goal"]["id"]

    # Bob knows the integer id but must not be able to act on it.
    assert client.delete(f"/goals/{goal_id}", headers=_auth(bob)).status_code == 404
    assert len(client.get("/goals", headers=_auth(alice)).json()["goals"]) == 1
    # The owner still can.
    assert client.delete(f"/goals/{goal_id}", headers=_auth(alice)).status_code == 200


# ---------- Password change ----------
def test_password_change_flow(client):
    email = _email("changer")
    session = _register(client, email)
    headers = _auth(session)

    assert client.post(
        "/auth/password",
        headers=headers,
        json={"current_password": "wrong", "new_password": "a new long password"},
    ).status_code == 403
    assert client.post(
        "/auth/password",
        headers=headers,
        json={"current_password": "a good long password", "new_password": "short"},
    ).status_code == 422
    assert client.post(
        "/auth/password",
        headers=headers,
        json={
            "current_password": "a good long password",
            "new_password": "a new long password",
        },
    ).status_code == 200

    assert client.post(
        "/auth/login", json={"email": email, "password": "a good long password"}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": email, "password": "a new long password"}
    ).status_code == 200


# ---------- Brute-force protection ----------
def test_login_is_rate_limited(client):
    target = _email("bruteforce")
    codes = [
        client.post(
            "/auth/login", json={"email": target, "password": f"wrong{i}"}
        ).status_code
        for i in range(12)
    ]
    assert 429 in codes, f"login was never rate limited: {codes}"
    assert codes.index(429) >= 8, "rate limited earlier than the configured allowance"


def test_registration_volume_is_rate_limited(client):
    """Successful signups count too, or account creation is unbounded."""
    codes = [
        client.post(
            "/auth/register",
            json={"email": _email("flood"), "password": "a good long password"},
        ).status_code
        for _ in range(13)
    ]
    assert 429 in codes, f"registration was never rate limited: {codes}"
    assert codes.count(201) <= 10, f"more signups allowed than the cap: {codes}"


# ---------- Deletion revokes access ----------
def test_deleting_an_account_invalidates_its_outstanding_tokens(client):
    session = _register(client, _email("gone"))
    headers = _auth(session)
    assert client.delete("/auth/me", headers=headers).status_code == 200
    # The token is still correctly signed and unexpired; the account is gone.
    assert client.get("/auth/me", headers=headers).status_code == 401
