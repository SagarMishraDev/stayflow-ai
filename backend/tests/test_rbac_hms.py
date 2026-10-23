"""HMS Phase 3 RBAC tests: expanded roles, permissions, token version.

Uses a plain TestClient so 401/403 behaviour is real. Users of non-admin
roles are created directly in the DB (following test_rbac.py patterns)
and tokens are minted with create_access_token including token_version.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.hotel_user import HotelUser
from tests._helpers import (
    future,
    make_guest,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
    uid,
)

plain = TestClient(app)
_PW = "rbac-hms-pass-123"


def _make_user(
    hotel_id: int, role: str, email: str | None = None, password: str = _PW
) -> HotelUser:
    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel_id,
            name=f"HMS {role}",
            email=email or f"{uid('hms-' + role)}@example.com",
            role=role,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # Detached copy of scalar fields we need after close.
        return user
    finally:
        db.close()


def _headers(user) -> dict:
    # Re-read token_version so tokens minted after bumps are current when
    # the caller passes a freshly fetched user; for plain creation tv=0.
    tv = getattr(user, "token_version", 0) or 0
    try:
        db = SessionLocal()
        try:
            fresh = db.get(HotelUser, user.id)
            if fresh is not None:
                tv = fresh.token_version or 0
        finally:
            db.close()
    except Exception:
        pass
    token = create_access_token(
        hotel_user_id=user.id, hotel_id=user.hotel_id, role=user.role, token_version=tv
    )
    return {"Authorization": f"Bearer {token}"}


def _payload(role: str) -> dict:
    return {
        "name": uid("New"),
        "email": f"{uid('hms-new')}@example.com",
        "password": "newstaff-pass-123",
        "role": role,
    }


def _make_order(hotel_id: int, headers: dict) -> dict:
    guest = make_guest(hotel_id)
    r = plain.post(
        "/api/v1/orders",
        json={"hotel_id": hotel_id, "guest_id": guest["id"], "order_type": "ROOM_SERVICE"},
        headers=headers,
    )
    ok(r, 201)
    return r.json()


def _make_booking(hotel_id: int, headers: dict) -> dict:
    room = make_room(hotel_id)
    guest = make_guest(hotel_id)
    start = future(40)
    seed_rates_availability(room["id"], start, 3)
    # seed helpers use shared client (hotel_admin token) — fine.
    r = plain.post(
        "/api/v1/bookings",
        json={
            "hotel_id": hotel_id,
            "guest_id": guest["id"],
            "room_id": room["id"],
            "check_in": str(start),
            "check_out": str(start + timedelta(days=2)),
            "number_of_guests": 1,
        },
        headers=headers,
    )
    ok(r, 201)
    return r.json()


def test_manager_creates_receptionist_ok():
    hotel = make_hotel()
    manager = _make_user(hotel["id"], "manager")
    r = plain.post("/api/v1/hotel-users", json=_payload("receptionist"), headers=_headers(manager))
    ok(r, 201)
    assert r.json()["role"] == "receptionist"


def test_manager_cannot_create_privileged_roles():
    hotel = make_hotel()
    manager = _make_user(hotel["id"], "manager")
    for role in ("hotel_admin", "manager", "super_admin"):
        r = plain.post("/api/v1/hotel-users", json=_payload(role), headers=_headers(manager))
        assert r.status_code == 403, (role, r.text)


def test_admin_cannot_create_super_admin_and_manager_can_create_operational():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    r = plain.post("/api/v1/hotel-users", json=_payload("super_admin"), headers=_headers(admin))
    assert r.status_code == 403, r.text
    # Admin can create a manager (staff.create_manager).
    r = plain.post("/api/v1/hotel-users", json=_payload("manager"), headers=_headers(admin))
    ok(r, 201)


def test_manager_self_escalation_blocked():
    hotel = make_hotel()
    manager = _make_user(hotel["id"], "manager")
    r = plain.patch(
        f"/api/v1/hotel-users/{manager.id}",
        json={"role": "hotel_admin"},
        headers=_headers(manager),
    )
    assert r.status_code == 403, r.text


def test_manager_can_update_operational_staff_but_not_admin():
    hotel = make_hotel()
    manager = _make_user(hotel["id"], "manager")
    recep = _make_user(hotel["id"], "receptionist")
    admin2 = _make_user(hotel["id"], "hotel_admin")
    r = plain.patch(
        f"/api/v1/hotel-users/{recep.id}", json={"name": "Renamed"}, headers=_headers(manager)
    )
    ok(r, 200)
    r = plain.patch(
        f"/api/v1/hotel-users/{admin2.id}", json={"name": "Nope"}, headers=_headers(manager)
    )
    assert r.status_code == 403, r.text
    # Manager cannot promote receptionist to manager.
    r = plain.patch(
        f"/api/v1/hotel-users/{recep.id}", json={"role": "manager"}, headers=_headers(manager)
    )
    assert r.status_code == 403, r.text


def test_receptionist_cannot_view_audit_logs():
    hotel = make_hotel()
    recep = _make_user(hotel["id"], "receptionist")
    r = plain.get("/api/v1/audit-logs", headers=_headers(recep))
    assert r.status_code == 403, r.text


def test_maintenance_cannot_view_audit_logs_but_manager_and_accountant_can():
    hotel = make_hotel()
    maint = _make_user(hotel["id"], "maintenance")
    r = plain.get("/api/v1/audit-logs", headers=_headers(maint))
    assert r.status_code == 403, r.text
    mgr = _make_user(hotel["id"], "manager")
    ok(plain.get("/api/v1/audit-logs", headers=_headers(mgr)), 200)
    acc = _make_user(hotel["id"], "accountant")
    ok(plain.get("/api/v1/audit-logs", headers=_headers(acc)), 200)


def test_kitchen_can_patch_order_but_cannot_create_users():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    order = _make_order(hotel["id"], _headers(admin))
    kitchen = _make_user(hotel["id"], "kitchen")
    r = plain.patch(
        f"/api/v1/orders/{order['id']}", json={"status": "PREPARING"}, headers=_headers(kitchen)
    )
    ok(r, 200)
    r = plain.post("/api/v1/hotel-users", json=_payload("staff"), headers=_headers(kitchen))
    assert r.status_code == 403, r.text


def test_housekeeping_cannot_patch_booking():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    booking = _make_booking(hotel["id"], _headers(admin))
    hk = _make_user(hotel["id"], "housekeeping")
    r = plain.patch(
        f"/api/v1/bookings/{booking['id']}",
        json={"booking_status": "CONFIRMED"},
        headers=_headers(hk),
    )
    assert r.status_code == 403, r.text
    # Receptionist (bookings.manage) can.
    recep = _make_user(hotel["id"], "receptionist")
    r = plain.patch(
        f"/api/v1/bookings/{booking['id']}",
        json={"booking_status": "CONFIRMED"},
        headers=_headers(recep),
    )
    ok(r, 200)


def test_deactivated_account_old_token_rejected():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    victim = _make_user(hotel["id"], "receptionist")
    victim_headers = _headers(victim)
    ok(plain.get("/api/v1/hotels", headers=victim_headers), 200)
    r = plain.patch(
        f"/api/v1/hotel-users/{victim.id}",
        json={"is_active": False},
        headers=_headers(admin),
    )
    ok(r, 200)
    r = plain.get("/api/v1/hotels", headers=victim_headers)
    assert r.status_code == 401, r.text


def test_role_change_revokes_old_token_and_fresh_login_works():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    target = _make_user(hotel["id"], "receptionist")
    old_headers = _headers(target)
    ok(plain.get("/api/v1/hotels", headers=old_headers), 200)
    r = plain.patch(
        f"/api/v1/hotel-users/{target.id}",
        json={"role": "kitchen"},
        headers=_headers(admin),
    )
    ok(r, 200)
    # Old token (old role + old tv) is revoked.
    r = plain.get("/api/v1/hotels", headers=old_headers)
    assert r.status_code == 401, r.text
    # Fresh login works and carries the new role / tv.
    r = plain.post("/api/v1/auth/login", json={"email": target.email, "password": _PW})
    ok(r, 200)
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ok(plain.get("/api/v1/hotels", headers=fresh), 200)


def test_password_change_revokes_old_token():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    target = _make_user(hotel["id"], "staff")
    old_headers = _headers(target)
    r = plain.patch(
        f"/api/v1/hotel-users/{target.id}",
        json={"password": "brand-new-pass-456"},
        headers=_headers(admin),
    )
    ok(r, 200)
    r = plain.get("/api/v1/hotels", headers=old_headers)
    assert r.status_code == 401, r.text
    r = plain.post(
        "/api/v1/auth/login", json={"email": target.email, "password": "brand-new-pass-456"}
    )
    ok(r, 200)


def test_cannot_deactivate_self():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    r = plain.patch(
        f"/api/v1/hotel-users/{admin.id}",
        json={"is_active": False},
        headers=_headers(admin),
    )
    assert r.status_code == 403, r.text


def test_cross_hotel_staff_list_is_scoped():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    admin_a = _make_user(hotel_a["id"], "hotel_admin")
    _make_user(hotel_b["id"], "receptionist")
    # Listing with explicit other-hotel id is forbidden for non-super.
    r = plain.get(
        "/api/v1/hotel-users", params={"hotel_id": hotel_b["id"]}, headers=_headers(admin_a)
    )
    assert r.status_code == 403, r.text
    # Default listing only contains own-hotel users.
    r = plain.get("/api/v1/hotel-users", headers=_headers(admin_a))
    ok(r, 200)
    assert all(u["hotel_id"] == hotel_a["id"] for u in r.json())
    # Cross-hotel single-user access is 403 via tenant check.
    db = SessionLocal()
    try:
        other = db.scalars(select(HotelUser).where(HotelUser.hotel_id == hotel_b["id"])).first()
        other_id = other.id
    finally:
        db.close()
    r = plain.get(f"/api/v1/hotel-users/{other_id}", headers=_headers(admin_a))
    assert r.status_code == 403, r.text


def test_department_roundtrip():
    hotel = make_hotel()
    admin = _make_user(hotel["id"], "hotel_admin")
    payload = _payload("housekeeping")
    payload["department"] = "housekeeping"
    r = plain.post("/api/v1/hotel-users", json=payload, headers=_headers(admin))
    ok(r, 201)
    assert r.json()["department"] == "housekeeping"
    uid_created = r.json()["id"]
    r = plain.patch(
        f"/api/v1/hotel-users/{uid_created}",
        json={"department": "operations"},
        headers=_headers(admin),
    )
    ok(r, 200)
    assert r.json()["department"] == "operations"
