import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seed  # noqa: E402
from app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "test.db")
    seed.build(db, force=True)
    app = create_app({"DATABASE": db, "SECRET_KEY": "test", "TESTING": True})
    return app.test_client()


def csrf(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s["csrf"]


def login(client, user="admin", password="admin123"):
    return client.post("/login", data={"username": user, "password": password, "csrf": csrf(client)})


def test_requires_login(client):
    assert client.get("/").status_code == 302


def test_wrong_password(client):
    resp = login(client, password="nope")
    assert b"Wrong username or password" in resp.data


def test_dashboard_and_list(client):
    login(client)
    assert b"Total assets" in client.get("/").data
    page = client.get("/assets?category=Laptop")
    assert page.status_code == 200 and b"LT-001" in page.data


def test_post_without_csrf_is_rejected(client):
    login(client)
    assert client.post("/assets/1/verify").status_code == 400


def test_viewer_cannot_edit(client):
    login(client, "viewer", "viewer123")
    assert client.get("/assets/new").status_code == 403


def test_handover_records_history(client):
    login(client)
    token = csrf(client)
    resp = client.post("/assets/1/handover", data={"to_holder": "5", "note": "test", "csrf": token},
                       follow_redirects=True)
    assert b"Handover recorded" in resp.data
    assert b"test" in client.get("/assets/1").data


def test_create_and_duplicate_code(client):
    login(client)
    form = {"code": "LT-900", "name": "Test Laptop", "category": "Laptop", "status": "in_storage",
            "location": "Head Office - Floor 1", "csrf": csrf(client)}
    assert b"Asset LT-900 added" in client.post("/assets/new", data=form, follow_redirects=True).data
    assert b"already exists" in client.post("/assets/new", data=form).data


def test_csv_export(client):
    login(client)
    resp = client.get("/assets/export.csv?status=repair")
    assert resp.mimetype == "text/csv"
    assert resp.data.splitlines()[0].startswith(b"Code,Name")


def test_open_redirect_blocked(client):
    client.get("/login")
    resp = client.post("/login?next=//evil.example", data={
        "username": "admin", "password": "admin123", "csrf": csrf(client)})
    assert resp.headers["Location"] == "/"
