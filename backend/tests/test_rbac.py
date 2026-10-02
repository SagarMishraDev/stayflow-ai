"""RBAC tests (Prompt-2 section 23): roles, user management, super-admin bypass.

Uses a plain ``TestClient`` (no auto-attached tokens) so the assertions
observe real 401/403 behaviour.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.hotel_user import HotelUser
from tests._helpers import make_hotel, make_room, ok, uid

plain = TestClient(app)

_STAFF_PASSWORD = "rbac-test-pass-123"


def _make_user(hotel_id: int, role: str, email: str | None = None) -> HotelUser:
    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel_id,
            name=f"RBAC {role}",
            email=email or f"{uid('rbac-' + role)}@example.com",
            role=role,
            password_hash=hash_password(_STAFF_PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers(user: HotelUser) -> dict:
    token = create_access_token(hotel_user_id=user.id, hotel_id=user.hotel_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


def _user_payload(role: str = "staff") -> dict:
    return {
        "name": uid("New Staff"),
        "email": f"{uid('newstaff')}@example.com",
        "password": "newstaff-pass-123",
        "role": role,
    }


def test_staff_cannot_manage_users():
    hotel = make_hotel()
    staff = _make_user(hotel["id"], "staff")
    headers = _headers(staff)
    target = _make_user(hotel["id"], "staff")

    r = plain.post("/api/v1/hotel-users", json=_user_payload(), headers=headers)
    assert r.status_code == 403, r.text

    r = plain.patch(
        f"/api/v1/hotel-users/{target.id}",
        json={"name": "Sneaky Rename"},
        headers=headers,
    )
    assert r.status_code == 403, r.text

    r = plain.delete(f"/api/v1/hotel-users/{target.id}", headers=headers)
    assert r.status_code == 403, r.text


def test_hotel_admin_can_manage_users():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    headers = _headers(admin)

    r = plain.post("/api/v1/hotel-users", json=_user_payload("staff"), headers=headers)
    ok(r, 201)
    created = r.json()
    assert created["role"] == "staff"
    assert created["hotel_id"] == hotel["id"]

    # Deactivate: PATCH with is_active=false.
    r = plain.patch(
        f"/api/v1/hotel-users/{created['id']}",
        json={"is_active": False},
        headers=headers,
    )
    ok(r, 200)
    assert r.json()["is_active"] is False

    # A hotel admin cannot mint super admins.
    r = plain.post("/api/v1/hotel-users", json=_user_payload("super_admin"), headers=headers)
    assert r.status_code == 403, r.text

    # Unknown roles are rejected.
    r = plain.post("/api/v1/hotel-users", json=_user_payload("owner"), headers=headers)
    assert r.status_code == 422, r.text

    # The management actions were audited.
    db = SessionLocal()
    try:
        actions = {
            row.action
            for row in db.scalars(select(AuditLog).where(AuditLog.hotel_id == hotel["id"])).all()
        }
    finally:
        db.close()
    assert "hotel_user.created" in actions
    assert "hotel_user.deactivated" in actions


def test_legacy_admin_role_keeps_managing_users():
    """Pre-RBAC ``"admin"`` role values keep working as HOTEL_ADMIN."""
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "admin")
    headers = _headers(admin)

    r = plain.post("/api/v1/hotel-users", json=_user_payload(), headers=headers)
    ok(r, 201)


def test_super_admin_cross_hotel_access_is_audited():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    room_b = make_room(hotel_b["id"])
    super_admin = _make_user(hotel_a["id"], "super_admin")
    headers = _headers(super_admin)

    # Cross-hotel reads succeed for a super admin ...
    r = plain.get(f"/api/v1/hotels/{hotel_b['id']}", headers=headers)
    ok(r, 200)
    assert r.json()["id"] == hotel_b["id"]

    r = plain.get(f"/api/v1/rooms/{room_b['id']}", headers=headers)
    ok(r, 200)

    # ... but every bypass is recorded prominently in the audit log.
    r = plain.get(
        "/api/v1/audit-logs",
        params={"hotel_id": hotel_b["id"], "action": "super_admin.cross_hotel_access"},
        headers=headers,
    )
    ok(r, 200)
    entries = r.json()
    assert len(entries) >= 2, entries
    assert all(e["actor_id"] == super_admin.id for e in entries)
    assert all(e["hotel_id"] == hotel_b["id"] for e in entries)

    # Same-hotel access by the super admin is *not* flagged as a bypass.
    db = SessionLocal()
    try:
        flagged = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "super_admin.cross_hotel_access",
                AuditLog.hotel_id == hotel_a["id"],
            )
        ).all()
    finally:
        db.close()
    assert flagged == []


def test_super_admin_can_create_user_in_another_hotel():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    super_admin = _make_user(hotel_a["id"], "super_admin")
    headers = _headers(super_admin)

    payload = _user_payload("hotel_admin")
    payload["hotel_id"] = hotel_b["id"]
    r = plain.post("/api/v1/hotel-users", json=payload, headers=headers)
    ok(r, 201)
    assert r.json()["hotel_id"] == hotel_b["id"]

    # A hotel admin may not do the same.
    admin = _make_user(hotel_a["id"], "hotel_admin")
    payload = _user_payload()
    payload["hotel_id"] = hotel_b["id"]
    r = plain.post("/api/v1/hotel-users", json=payload, headers=_headers(admin))
    assert r.status_code == 403, r.text


def test_forged_role_claim_is_rejected():
    """A hand-crafted token with a forged role claim (valid signature) is 401.

    The token's role claim must match the role stored on the user row; a
    staff user minting a ``super_admin`` claim gets no extra rights.
    """
    hotel = make_hotel()
    staff = _make_user(hotel["id"], "staff")

    forged = create_access_token(
        hotel_user_id=staff.id,
        hotel_id=hotel["id"],
        role="super_admin",  # does not match the account's "staff" role
    )
    forged_headers = {"Authorization": f"Bearer {forged}"}

    r = plain.get("/api/v1/hotels", headers=forged_headers)
    assert r.status_code == 401, r.text

    r = plain.post("/api/v1/hotel-users", json=_user_payload(), headers=forged_headers)
    assert r.status_code == 401, r.text


def test_role_checks_use_the_account_not_just_the_claim():
    """Even a *valid* token for a staff account cannot manage users."""
    hotel = make_hotel()
    staff = _make_user(hotel["id"], "staff")
    r = plain.get("/api/v1/hotel-users", headers=_headers(staff))
    ok(r, 200)  # reading the staff list is fine ...
    r = plain.post("/api/v1/hotel-users", json=_user_payload(), headers=_headers(staff))
    assert r.status_code == 403  # ... managing it is not
