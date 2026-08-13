def test_create_and_get_project(client, admin_headers):
    r = client.post("/api/projects", headers=admin_headers, json={
        "name": "Proj A", "email": "a@acme.com",
    })
    assert r.status_code == 200
    pid = r.json()["id"]

    got = client.get(f"/api/projects/{pid}", headers=admin_headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Proj A"


def test_update_project_status(client, admin_headers, project):
    r = client.put(f"/api/projects/{project['id']}", headers=admin_headers, json={"status": "inactive"})
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"


def _project_editor_headers(client, admin_headers):
    """A user with project.edit but no project memberships.
    Idempotent: reuses the role/user across tests instead of erroring on the second call."""
    role_name = "Project Editor (no scope)"
    roles = client.get("/api/roles", headers=admin_headers).json()
    role = next((r for r in roles if r["name"] == role_name), None)
    if role is None:
        role = client.post("/api/roles", headers=admin_headers, json={
            "name": role_name,
            "permission_codes": ["project.edit"],
        }).json()

    email = "editor-no-scope@reach.io"
    login = client.post("/api/auth/login", data={"username": email, "password": "Editor@123"})
    if login.status_code != 200:
        client.post("/api/users", headers=admin_headers, json={
            "name": "Scopeless Editor", "email": email, "password": "Editor@123", "role_id": role["id"],
        })
        login = client.post("/api/auth/login", data={"username": email, "password": "Editor@123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_non_member_cannot_update_project(client, admin_headers, project):
    headers = _project_editor_headers(client, admin_headers)
    r = client.put(f"/api/projects/{project['id']}", headers=headers, json={"status": "inactive"})
    assert r.status_code == 403
