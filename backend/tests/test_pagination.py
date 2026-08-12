"""Pagination on list endpoints (P1.6/G7): ?page=&page_size= + X-Total-Count,
applied by default so a large table can no longer come back unbounded.
Covers the four endpoints named in the master spec's Files line --
campaigns, recipients, templates, users.
"""
import uuid

from app.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from tests.conftest import make_campaign, upload_dataset


def test_campaigns_default_page_size_and_total_count(client, admin_headers, project):
    for i in range(DEFAULT_PAGE_SIZE + 5):
        make_campaign(client, admin_headers, project["id"], name=f"PagCamp{i}")

    r = client.get("/api/campaigns", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == DEFAULT_PAGE_SIZE
    assert int(r.headers["x-total-count"]) >= DEFAULT_PAGE_SIZE + 5


def test_campaigns_page_two_returns_disjoint_results(client, admin_headers, project):
    names = [f"PageSplit{i}" for i in range(DEFAULT_PAGE_SIZE + 5)]
    for n in names:
        make_campaign(client, admin_headers, project["id"], name=n)

    page1 = client.get("/api/campaigns", headers=admin_headers,
                        params={"page": 1, "page_size": 10}).json()
    page2 = client.get("/api/campaigns", headers=admin_headers,
                        params={"page": 2, "page_size": 10}).json()
    ids1 = {c["id"] for c in page1}
    ids2 = {c["id"] for c in page2}
    assert len(page1) == 10
    assert len(page2) == 10
    assert ids1.isdisjoint(ids2)


def test_page_size_capped_at_max(client, admin_headers):
    r = client.get("/api/campaigns", headers=admin_headers, params={"page_size": 1000})
    assert r.status_code == 422  # over the ge/le bound -- rejected, not silently clamped


def test_page_size_at_max_is_allowed(client, admin_headers):
    r = client.get("/api/campaigns", headers=admin_headers, params={"page_size": MAX_PAGE_SIZE})
    assert r.status_code == 200
    assert len(r.json()) <= MAX_PAGE_SIZE


def test_recipients_paginated(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    csv = "Name,Email Address,Mobile Number\n" + "".join(
        f"P{i},p{i}@example.com,90000000{i:02d}\n" for i in range(DEFAULT_PAGE_SIZE + 3)
    )
    imported = upload_dataset(client, admin_headers, c["id"], csv)
    assert imported.status_code == 200, imported.text

    r = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) == DEFAULT_PAGE_SIZE
    assert int(r.headers["x-total-count"]) == DEFAULT_PAGE_SIZE + 3

    page2 = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                        params={"page": 2}).json()
    assert len(page2) == 3


def test_templates_paginated(client, admin_headers):
    for i in range(DEFAULT_PAGE_SIZE + 4):
        r = client.post("/api/templates", headers=admin_headers, json={
            "name": f"PagTpl{i}", "channel": "email",
            "email_content": {"subject": "Hi", "fields": {}},
        })
        assert r.status_code == 200, r.text

    r = client.get("/api/templates", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) == DEFAULT_PAGE_SIZE
    assert int(r.headers["x-total-count"]) >= DEFAULT_PAGE_SIZE + 4


def test_users_paginated(client, admin_headers):
    role = client.get("/api/roles", headers=admin_headers).json()[0]
    unique = uuid.uuid4().hex[:8]
    for i in range(DEFAULT_PAGE_SIZE + 2):
        r = client.post("/api/users", headers=admin_headers, json={
            "name": f"Pag User {i}", "email": f"paguser{unique}{i}@example.com",
            "password": "Passw0rd!23", "role_id": role["id"],
        })
        assert r.status_code == 200, r.text

    r = client.get("/api/users", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) == DEFAULT_PAGE_SIZE
    assert int(r.headers["x-total-count"]) >= DEFAULT_PAGE_SIZE + 2
