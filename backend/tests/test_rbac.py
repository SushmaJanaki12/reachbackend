def test_user_cannot_list_users(client, user_headers):
    r = client.get("/api/users", headers=user_headers)
    assert r.status_code == 403


def test_user_cannot_create_project(client, user_headers):
    r = client.post("/api/projects", headers=user_headers, json={"name": "x", "email": "x@y.com"})
    assert r.status_code == 403


def test_user_cannot_manage_roles(client, user_headers):
    r = client.post("/api/roles", headers=user_headers, json={"name": "x", "permission_codes": []})
    assert r.status_code == 403


def test_user_sees_only_assigned_projects(client, admin_headers, user_headers):
    # user id
    users = client.get("/api/users", headers=admin_headers).json()
    uid = next(u["id"] for u in users if u["email"] == "user@reach.io")

    before = client.get("/api/projects", headers=user_headers).json()

    # admin creates a project assigned to the user
    p = client.post("/api/projects", headers=admin_headers, json={
        "name": "Scoped Project", "email": "scoped@acme.com", "member_ids": [uid],
    }).json()

    after = client.get("/api/projects", headers=user_headers).json()
    assert len(after) == len(before) + 1
    assert any(x["id"] == p["id"] for x in after)


def test_admin_role_cannot_be_edited(client, admin_headers):
    roles = client.get("/api/roles", headers=admin_headers).json()
    admin_role = next(r for r in roles if r["name"] == "Admin")
    r = client.put(f"/api/roles/{admin_role['id']}", headers=admin_headers,
                   json={"name": "Admin", "permission_codes": []})
    assert r.status_code == 400
