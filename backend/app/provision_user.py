import argparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Organization,
    SecurityAuditEvent,
    User,
    UserRole,
    UserSession,
    new_id,
    utcnow,
)


def provision_user(
    db: Session,
    *,
    org_id: str,
    org_name: str | None,
    email: str,
    role: UserRole,
    issuer: str,
    subject: str,
    active: bool,
) -> User:
    normalized_email = email.strip().lower()
    normalized_issuer = issuer.strip().rstrip("/")
    normalized_subject = subject.strip()
    if "@" not in normalized_email or not normalized_issuer or not normalized_subject:
        raise ValueError("A valid email, OIDC issuer, and OIDC subject are required")
    organization = db.get(Organization, org_id)
    if organization is None:
        if not org_name or not org_name.strip():
            raise ValueError(f"Organization {org_id!r} does not exist; provide --org-name")
        db.add(Organization(id=org_id, name=org_name.strip()))
        db.flush()

    by_email = db.scalar(select(User).where(User.email == normalized_email))
    by_identity = db.scalar(
        select(User).where(
            User.oidc_issuer == normalized_issuer,
            User.oidc_subject == normalized_subject,
        )
    )
    if by_email and by_identity and by_email.id != by_identity.id:
        raise ValueError("The email and OIDC identity belong to different users")
    user = by_identity or by_email
    created = user is None
    if user is None:
        user = User(id=new_id("usr"), org_id=org_id, email=normalized_email)
        db.add(user)
    elif user.org_id != org_id:
        raise ValueError("The user already belongs to a different organization")

    user.email = normalized_email
    user.role = role
    user.is_active = active
    user.oidc_issuer = normalized_issuer
    user.oidc_subject = normalized_subject
    db.flush()
    if not active:
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
    db.add(
        SecurityAuditEvent(
            org_id=user.org_id,
            user_id=user.id,
            action="user_provisioned" if created else "user_updated",
            outcome="success",
            details={"role": role.value, "active": active, "issuer": normalized_issuer},
        )
    )
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or update an OIDC dashboard user")
    parser.add_argument("--org", required=True, dest="org_id")
    parser.add_argument("--org-name", help="Create the organization when it does not exist")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=[role.value for role in UserRole], required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument(
        "--inactive", action="store_true", help="Disable the user and revoke sessions"
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        user = provision_user(
            db,
            org_id=args.org_id,
            org_name=args.org_name,
            email=args.email,
            role=UserRole(args.role),
            issuer=args.issuer,
            subject=args.subject,
            active=not args.inactive,
        )
        print(f"{user.id} {user.email} {user.role.value} active={user.is_active}")


if __name__ == "__main__":
    main()
