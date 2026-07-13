from app.database import SessionLocal
from app.models import Organization, Project, User, UserRole


def seed() -> None:
    with SessionLocal() as db:
        acme = Organization(id="org_acme", name="Acme Skincare")
        beta = Organization(id="org_beta", name="Beta Finance")
        db.merge(acme)
        db.merge(beta)
        db.flush()
        db.merge(
            User(
                id="usr_alice",
                org_id=acme.id,
                email="alice@acme.com",
                role=UserRole.owner,
            )
        )
        db.merge(
            User(
                id="usr_bob",
                org_id=beta.id,
                email="bob@beta.com",
                role=UserRole.owner,
            )
        )
        db.merge(
            Project(
                id="prj_acme_demo",
                org_id=acme.id,
                name="Acme Skincare",
                domain="acmeskincare.com",
                competitors=["glowco.com", "naturalskin.com"],
            )
        )
        db.merge(
            Project(
                id="prj_beta_demo",
                org_id=beta.id,
                name="Beta Finance",
                domain="betafinance.com",
                competitors=["finwise.com", "moneybeam.com"],
            )
        )
        db.commit()


if __name__ == "__main__":
    seed()
