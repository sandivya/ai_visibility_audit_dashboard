from app.database import SessionLocal
from app.models import Audit
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError


def test_user_can_create_and_list_project(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/projects",
        headers=alice_headers,
        json={"name": "New Brand", "domain": "newbrand.com", "competitors": ["rival.com"]},
    )
    assert response.status_code == 201
    projects = client.get("/api/projects", headers=alice_headers).json()["items"]
    assert projects[0]["name"] == "New Brand"
    assert all(project["id"] != "prj_beta_demo" for project in projects)


def test_cross_org_project_is_hidden(client: TestClient, alice_headers: dict[str, str]) -> None:
    response = client.get("/api/projects/prj_beta_demo", headers=alice_headers)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Project not found"


def test_project_validation(client: TestClient, alice_headers: dict[str, str]) -> None:
    empty = client.post(
        "/api/projects", headers=alice_headers, json={"name": " ", "domain": "ok.com"}
    )
    invalid = client.post(
        "/api/projects", headers=alice_headers, json={"name": "Valid", "domain": "not a domain"}
    )
    assert empty.status_code == 422
    assert invalid.status_code == 422
    assert "valid domain" in invalid.json()["error"]["message"].lower()


def test_auth_is_required(client: TestClient) -> None:
    assert client.get("/api/projects").status_code == 401


def test_signed_session_login(client: TestClient) -> None:
    response = client.post("/api/auth/sessions", json={"user_id": "usr_alice"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/projects").status_code == 200
    assert (
        client.get("/api/projects", headers={"Cookie": "visibility_session=tampered"}).status_code
        == 401
    )


def test_project_cursor_pagination(client: TestClient, alice_headers: dict[str, str]) -> None:
    for index in range(3):
        response = client.post(
            "/api/projects",
            headers=alice_headers,
            json={"name": f"Brand {index}", "domain": f"brand{index}.example"},
        )
        assert response.status_code == 201
    first = client.get("/api/projects?limit=2", headers=alice_headers).json()
    second = client.get(
        f"/api/projects?limit=2&cursor={first['next_cursor']}", headers=alice_headers
    ).json()
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert len(first["items"]) == 2
    assert first_ids.isdisjoint(second_ids)


def test_database_rejects_cross_tenant_project_link() -> None:
    with SessionLocal() as db:
        db.add(
            Audit(
                org_id="org_acme",
                project_id="prj_beta_demo",
                idempotency_key="invalid-tenant-link",
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-tenant foreign key should have failed")
        except IntegrityError:
            db.rollback()
