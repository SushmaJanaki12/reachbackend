"""Self-service forgot/reset-password flow (P1.7, G4)."""
from datetime import datetime, timedelta, timezone

import app.routers.auth as auth_mod
from app.database import SessionLocal
from app.mailer import MailError
from app.models import PasswordResetToken, User


def _fake_send(monkeypatch):
    calls = []
    monkeypatch.setattr(auth_mod, "send_system_email",
                        lambda db, to, subject, body, is_html=False: (calls.append((to, subject, body)), "id")[1])
    return calls


def _latest_token(user_id: int) -> str:
    db = SessionLocal()
    try:
        row = db.query(PasswordResetToken).filter_by(user_id=user_id).order_by(PasswordResetToken.id.desc()).first()
        return row.token
    finally:
        db.close()


def test_forgot_password_unknown_email_returns_generic_ok(client, monkeypatch):
    calls = _fake_send(monkeypatch)
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert calls == []  # no user found -- nothing sent


def test_forgot_password_known_email_creates_token_and_sends_email(client, monkeypatch):
    calls = _fake_send(monkeypatch)
    r = client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(calls) == 1
    to, subject, body = calls[0]
    assert to == "admin@reach.io"
    assert "reset" in subject.lower()
    assert "reset-password?token=" in body


def test_forgot_password_response_identical_for_known_and_unknown_email(client, monkeypatch):
    """The whole point of the generic response -- an attacker probing emails
    must not be able to tell registered accounts from unregistered ones."""
    _fake_send(monkeypatch)
    known = client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"}).json()
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"}).json()
    assert known == unknown


def test_forgot_password_mail_failure_still_returns_generic_ok(client, monkeypatch):
    def _raise(*a, **k):
        raise MailError("smtp exploded")
    monkeypatch.setattr(auth_mod, "send_system_email", _raise)
    r = client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # Token was still created despite the send failure -- not the caller's problem to know about.
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="admin@reach.io").first()
        assert db.query(PasswordResetToken).filter_by(user_id=user.id, used_at=None).count() == 1
    finally:
        db.close()


def test_reset_password_round_trip_and_new_password_works(client, monkeypatch):
    _fake_send(monkeypatch)
    client.post("/api/auth/forgot-password", json={"email": "user@reach.io"})
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email="user@reach.io").first().id
    finally:
        db.close()
    token = _latest_token(user_id)

    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPassw0rd!"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    old_login = client.post("/api/auth/login", data={"username": "user@reach.io", "password": "User@123"})
    assert old_login.status_code == 400

    new_login = client.post("/api/auth/login", data={"username": "user@reach.io", "password": "NewPassw0rd!"})
    assert new_login.status_code == 200

    # restore the seeded password so other test modules relying on it aren't affected
    client.post("/api/auth/forgot-password", json={"email": "user@reach.io"})
    token2 = _latest_token(user_id)
    r2 = client.post("/api/auth/reset-password", json={"token": token2, "new_password": "User@123"})
    assert r2.status_code == 200, r2.text


def test_reset_password_token_is_single_use(client, monkeypatch):
    _fake_send(monkeypatch)
    client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email="admin@reach.io").first().id
    finally:
        db.close()
    token = _latest_token(user_id)

    first = client.post("/api/auth/reset-password", json={"token": token, "new_password": "Admin@123"})
    assert first.status_code == 200, first.text

    second = client.post("/api/auth/reset-password", json={"token": token, "new_password": "SomethingElse1"})
    assert second.status_code == 400
    assert "invalid" in second.json()["detail"].lower() or "expired" in second.json()["detail"].lower()


def test_reset_password_rejects_expired_token(client, monkeypatch):
    _fake_send(monkeypatch)
    client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email="admin@reach.io").first().id
        row = db.query(PasswordResetToken).filter_by(user_id=user_id).order_by(PasswordResetToken.id.desc()).first()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        token = row.token
        db.commit()
    finally:
        db.close()

    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": "Admin@123"})
    assert r.status_code == 400


def test_reset_password_rejects_unknown_token(client):
    r = client.post("/api/auth/reset-password", json={"token": "not-a-real-token", "new_password": "Admin@123"})
    assert r.status_code == 400


def test_reset_password_rejects_short_password(client, monkeypatch):
    _fake_send(monkeypatch)
    client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email="admin@reach.io").first().id
    finally:
        db.close()
    token = _latest_token(user_id)

    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": "short"})
    assert r.status_code == 400

    db = SessionLocal()
    try:
        assert db.query(PasswordResetToken).filter_by(token=token).first().used_at is None
    finally:
        db.close()


def test_forgot_password_invalidates_prior_unused_token(client, monkeypatch):
    _fake_send(monkeypatch)
    client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email="admin@reach.io").first().id
    finally:
        db.close()
    first_token = _latest_token(user_id)

    client.post("/api/auth/forgot-password", json={"email": "admin@reach.io"})
    second_token = _latest_token(user_id)
    assert first_token != second_token

    stale = client.post("/api/auth/reset-password", json={"token": first_token, "new_password": "Admin@123"})
    assert stale.status_code == 400

    fresh = client.post("/api/auth/reset-password", json={"token": second_token, "new_password": "Admin@123"})
    assert fresh.status_code == 200, fresh.text
