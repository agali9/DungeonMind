from __future__ import annotations


def test_register_valid_redirects_to_home(client):
    res = client.post(
        "/auth/register",
        data={"email": "a@example.com", "display_name": "A", "password": "password123"},
    )
    assert res.status_code == 302
    assert res.location.endswith("/")


def test_register_short_password(client):
    res = client.post(
        "/auth/register",
        data={"email": "a2@example.com", "display_name": "A", "password": "short"},
    )
    assert res.status_code == 400


def test_register_invalid_email(client):
    res = client.post(
        "/auth/register",
        data={"email": "bad-email", "display_name": "A", "password": "password123"},
    )
    assert res.status_code == 400


def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "display_name": "A", "password": "password123"}
    assert client.post("/auth/register", data=payload).status_code == 302
    assert client.post("/auth/register", data=payload).status_code == 400


def test_login_correct_credentials(client):
    client.post("/auth/register", data={"email": "ok@example.com", "display_name": "A", "password": "password123"})
    client.post("/auth/logout")
    res = client.post("/auth/login", data={"email": "ok@example.com", "password": "password123"})
    assert res.status_code == 302


def test_login_wrong_password(client):
    client.post("/auth/register", data={"email": "wrong@example.com", "display_name": "A", "password": "password123"})
    client.post("/auth/logout")
    res = client.post("/auth/login", data={"email": "wrong@example.com", "password": "not-it"})
    assert res.status_code == 401


def test_login_unknown_email(client):
    res = client.post("/auth/login", data={"email": "unknown@example.com", "password": "password123"})
    assert res.status_code == 401


def test_logout_requires_login(client):
    res = client.post("/auth/logout")
    assert res.status_code == 302
    assert "/auth/login" in res.location


def test_logout_redirects_to_login(client):
    client.post("/auth/register", data={"email": "logout@example.com", "display_name": "A", "password": "password123"})
    res = client.post("/auth/logout")
    assert res.status_code == 302
    assert "/auth/login" in res.location


def test_login_rate_limit(client):
    client.post("/auth/register", data={"email": "rate@example.com", "display_name": "A", "password": "password123"})
    client.post("/auth/logout")
    for _ in range(5):
        assert client.post("/auth/login", data={"email": "rate@example.com", "password": "bad"}).status_code == 401
    limited = client.post("/auth/login", data={"email": "rate@example.com", "password": "bad"})
    assert limited.status_code == 429
