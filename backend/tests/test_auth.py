def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_success(client):
    r = client.post("/api/auth/login", data={"username": "admin@reach.io", "password": "Admin@123"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", data={"username": "admin@reach.io", "password": "nope"})
    assert r.status_code == 400


def test_me_admin(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["role"]["name"] == "Admin"
    assert "role.manage" in body["permissions"]
    assert len(body["permissions"]) >= 15


def test_me_user_scoped(client, user_headers):
    r = client.get("/api/auth/me", headers=user_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["role"]["name"] == "User"
    assert "role.manage" not in body["permissions"]
    assert "campaign.create" in body["permissions"]


def test_me_unauthenticated(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
