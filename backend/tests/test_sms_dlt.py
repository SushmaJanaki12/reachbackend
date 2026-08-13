from tests.conftest import make_campaign

OTP = ("Dear customer, use this One Time Password {#var#} to verify your "
       "MISTA EATS account. This OTP will be valid for the next 10 mins.")


def _template(client, admin_headers, tid="1707168726031344535"):
    return client.post("/api/sms/templates", headers=admin_headers, json={
        "name": "OTP", "template_id": tid, "sender_id": "MISTAE", "body": OTP,
    }).json()


def test_create_and_list_template(client, admin_headers):
    tpl = _template(client, admin_headers)
    assert tpl["template_id"] == "1707168726031344535"
    lst = client.get("/api/sms/templates", headers=admin_headers).json()
    assert any(t["id"] == tpl["id"] for t in lst)


def test_validate_matching(client, admin_headers):
    tpl = _template(client, admin_headers)
    msg = OTP.replace("{#var#}", "{{OTP}}")
    r = client.post("/api/sms/validate", headers=admin_headers, json={"template_ref": tpl["id"], "message": msg})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_validate_nonmatching(client, admin_headers):
    tpl = _template(client, admin_headers)
    r = client.post("/api/sms/validate", headers=admin_headers,
                    json={"template_ref": tpl["id"], "message": "Autumn sale 20% off at {{Company}}"})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_user_cannot_create_template(client, user_headers):
    r = client.post("/api/sms/templates", headers=user_headers,
                    json={"name": "x", "template_id": "1", "body": "y"})
    assert r.status_code == 403
