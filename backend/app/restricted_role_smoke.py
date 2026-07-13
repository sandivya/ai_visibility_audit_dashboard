import argparse


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def api_create_phase() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        login = client.post("/api/auth/sessions", json={"user_id": "usr_alice"})
        require(login.status_code == 200, login.text)
        created_project = client.post(
            "/api/projects",
            json={"name": "Restricted role smoke", "domain": "restricted-role.example"},
        )
        require(created_project.status_code == 201, created_project.text)
        cross_tenant = client.get("/api/projects/prj_beta_demo")
        require(cross_tenant.status_code == 404, cross_tenant.text)
        accepted = client.post(
            "/api/projects/prj_acme_demo/audits",
            headers={"Idempotency-Key": "restricted-role-smoke-v1"},
        )
        require(accepted.status_code == 202, accepted.text)


def worker_phase() -> None:
    from app.services import run_worker_once

    require(run_worker_once("restricted-role-smoke-worker"), "The worker did not claim an audit")


def api_complete_phase() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        login = client.post("/api/auth/sessions", json={"user_id": "usr_alice"})
        require(login.status_code == 200, login.text)
        audits = client.get("/api/projects/prj_acme_demo/audits?limit=1").json()["items"]
        require(audits and audits[0]["status"] == "completed", "Audit was not completed")
        recommendations = client.get(
            f"/api/audits/{audits[0]['id']}/recommendations?limit=1"
        ).json()["items"]
        require(recommendations, "No recommendation was generated")
        updated = client.patch(
            f"/api/recommendations/{recommendations[0]['id']}",
            json={"status": "in_progress"},
        )
        require(updated.status_code == 200, updated.text)
        require(updated.json()["status"] == "in_progress", "Recommendation update was lost")
        logout = client.delete("/api/auth/sessions")
        require(logout.status_code == 204, logout.text)
        rejected = client.get("/api/projects")
        require(rejected.status_code == 401, rejected.text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise API and worker restricted database roles"
    )
    parser.add_argument("phase", choices=("create", "worker", "complete"))
    phase = parser.parse_args().phase
    if phase == "create":
        api_create_phase()
    elif phase == "worker":
        worker_phase()
    else:
        api_complete_phase()


if __name__ == "__main__":
    main()
