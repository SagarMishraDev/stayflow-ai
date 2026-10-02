"""Auth tests (Prompt-1 section 3): argon2 staff login, JWT auth, tenant isolation.

Uses a plain ``TestClient`` (no auto-attached tokens) so the assertions below
observe real 401/403 behaviour. Hotel/user fixtures come from ``tests._helpers``.
"""

from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.hotel_user import HotelUser
from tests._helpers import make_guest, make_hotel, make_room, ok, register_hotel_token, uid

plain = TestClient(app)
settings = get_settings()

LOGIN_PASSWORD = "auth-test-pass-123"


def _make_staff(hotel_id: int, email: str | None = None) -> HotelUser:
    email = email or f"{uid('authuser')}@example.com"
    db = SessionLocal()
    try:
        user = HotelUser(
            hotel_id=hotel_id,
            name="Auth Tester",
            email=email,
            role="admin",
            password_hash=hash_password(LOGIN_PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_success_returns_jwt():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])

    r = plain.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": LOGIN_PASSWORD},
    )
    ok(r, 200)
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    claims = jwt.decode(
        body["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    assert claims["hotel_id"] == hotel["id"]
    assert claims["hotel_user_id"] == user.id
    assert claims["role"] == "admin"

    # The issued token authenticates a protected endpoint.
    r = plain.get("/api/v1/hotels", headers=_auth_headers(body["access_token"]))
    ok(r, 200)


def test_login_wrong_password_is_401():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])

    r = plain.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "definitely-wrong-password"},
    )
    assert r.status_code == 401, r.text


def test_login_unknown_email_is_401():
    make_hotel()
    r = plain.post(
        "/api/v1/auth/login",
        json={"email": f"{uuid4().hex}@example.com", "password": LOGIN_PASSWORD},
    )
    assert r.status_code == 401, r.text


def test_protected_endpoints_require_token():
    hotel = make_hotel()
    room = make_room(hotel["id"])

    assert plain.get("/api/v1/hotels").status_code == 401
    assert plain.get("/api/v1/db-check").status_code == 401
    assert plain.get(f"/api/v1/rooms/{room['id']}").status_code == 401
    assert (
        plain.post(
            "/api/v1/rooms",
            json={"hotel_id": hotel["id"], "room_type": "X", "total_rooms": 1},
        ).status_code
        == 401
    )
    assert plain.post("/api/v1/hotel-users", json={}).status_code == 401


def test_expired_token_is_401():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])
    token = create_access_token(
        hotel_user_id=user.id,
        hotel_id=hotel["id"],
        role=user.role,
        expires_minutes=-1,
    )
    r = plain.get("/api/v1/hotels", headers=_auth_headers(token))
    assert r.status_code == 401, r.text


def test_invalid_and_wrong_secret_tokens_are_401():
    hotel = make_hotel()
    user = _make_staff(hotel["id"])

    r = plain.get("/api/v1/hotels", headers=_auth_headers("not-a-real-token"))
    assert r.status_code == 401, r.text

    forged = jwt.encode(
        {"sub": str(user.id), "hotel_user_id": user.id, "hotel_id": hotel["id"]},
        "wrong-secret-key",
        algorithm="HS256",
    )
    r = plain.get("/api/v1/hotels", headers=_auth_headers(forged))
    assert r.status_code == 401, r.text


def test_cross_hotel_access_is_forbidden():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    room_b = make_room(hotel_b["id"])
    token_a = register_hotel_token(hotel_a["id"])
    headers_a = _auth_headers(token_a)

    # Item routes: hotel A's token on hotel B's existing objects -> 403.
    r = plain.get(f"/api/v1/rooms/{room_b['id']}", headers=headers_a)
    assert r.status_code == 403, r.text

    r = plain.get(f"/api/v1/hotels/{hotel_b['id']}", headers=headers_a)
    assert r.status_code == 403, r.text

    # Create routes: hotel_id in the body pointing at another hotel -> 403.
    r = plain.post(
        "/api/v1/rooms",
        json={
            "hotel_id": hotel_b["id"],
            "room_type": "Sneaky",
            "capacity": 2,
            "total_rooms": 1,
        },
        headers=headers_a,
    )
    assert r.status_code == 403, r.text

    # Collection routes: scoped to the caller's hotel; no leakage.
    r = plain.get("/api/v1/rooms", headers=headers_a)
    ok(r, 200)
    assert all(room["hotel_id"] == hotel_a["id"] for room in r.json())

    # PATCH must not reassign a record to another hotel's hotel room.
    room_a = make_room(hotel_a["id"])
    guest_a = make_guest(hotel_a["id"])
    r = plain.post(
        "/api/v1/hotel-rooms",
        json={
            "hotel_id": hotel_a["id"],
            "room_id": room_a["id"],
            "room_number": "101",
        },
        headers=headers_a,
    )
    ok(r, 201)
    hotel_room_a = r.json()
    r = plain.post(
        "/api/v1/hotel-rooms",
        json={
            "hotel_id": hotel_b["id"],
            "room_id": room_b["id"],
            "room_number": "201",
        },
        headers=_auth_headers(register_hotel_token(hotel_b["id"])),
    )
    ok(r, 201)
    hotel_room_b = r.json()
    r = plain.post(
        "/api/v1/orders",
        json={
            "hotel_id": hotel_a["id"],
            "guest_id": guest_a["id"],
            "room_id": hotel_room_a["id"],
            "order_type": "ROOM_SERVICE",
        },
        headers=headers_a,
    )
    ok(r, 201)
    order_a = r.json()
    r = plain.patch(
        f"/api/v1/orders/{order_a['id']}",
        json={"room_id": hotel_room_b["id"]},
        headers=headers_a,
    )
    assert r.status_code == 403, r.text
    # ...nor create an order pointing at another hotel's hotel room.
    r = plain.post(
        "/api/v1/orders",
        json={
            "hotel_id": hotel_a["id"],
            "guest_id": guest_a["id"],
            "room_id": hotel_room_b["id"],
            "order_type": "ROOM_SERVICE",
        },
        headers=headers_a,
    )
    assert r.status_code == 403, r.text


def test_staff_crud_stores_argon2_hash():
    hotel = make_hotel()
    admin_token = register_hotel_token(hotel["id"])
    headers = _auth_headers(admin_token)
    email = f"{uid('staffer')}@example.com"

    r = plain.post(
        "/api/v1/hotel-users",
        json={
            "name": "Front Desk",
            "email": email,
            "password": "frontdesk-pass-123",
            "role": "staff",
        },
        headers=headers,
    )
    ok(r, 201)
    created = r.json()
    assert "password" not in created
    assert "password_hash" not in created

    db = SessionLocal()
    try:
        stored = db.scalars(select(HotelUser).where(HotelUser.email == email)).one()
        assert stored.password_hash != "frontdesk-pass-123"
        assert stored.password_hash.startswith("$argon2id$")
    finally:
        db.close()

    # The new user can log in with the plaintext password.
    r = plain.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "frontdesk-pass-123"},
    )
    ok(r, 200)

    # Another hotel's admin cannot touch this hotel's users.
    other = make_hotel()
    other_token = register_hotel_token(other["id"])
    r = plain.get(
        f"/api/v1/hotel-users/{created['id']}",
        headers=_auth_headers(other_token),
    )
    assert r.status_code == 403, r.text
