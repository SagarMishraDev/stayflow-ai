"""Hotel staff authentication: argon2 password hashing + JWT bearer tokens.

Role-based access control lives here too: :func:`require_roles` is a
dependency factory built on :func:`get_current_user` that restricts an
endpoint to the given staff roles (403 otherwise). The role model itself
is documented in :mod:`app.core.roles`.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.roles import StaffRole, normalize_role
from app.db.session import get_db
from app.models.hotel_user import HotelUser

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with argon2. Never store plaintext."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time-ish verification of a password against an argon2 hash."""
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        # Malformed stored hash: treat as a mismatch, never crash login.
        return False


def create_access_token(
    *,
    hotel_user_id: int,
    hotel_id: int,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """Mint a signed JWT for a hotel staff user."""
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    )
    payload = {
        "sub": str(hotel_user_id),
        "hotel_user_id": hotel_user_id,
        "hotel_id": hotel_id,
        "role": role,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT, raising 401 on expired/invalid tokens."""
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token") from None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db, scope="function"),
) -> HotelUser:
    """FastAPI dependency: the authenticated, active hotel staff user.

    Reads the ``Authorization: Bearer <token>`` header. Raises 401 when the
    header is missing, the token is invalid or expired, the user no longer
    exists, or the user has been deactivated.

    The token's ``role`` claim is cross-checked against the role stored on
    the user row: a hand-crafted token whose claims don't match the account
    (e.g. a staff user minting a ``super_admin`` claim) is rejected with
    401, so role escalation requires a real role change in the database.
    """
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Not authenticated")

    payload = decode_access_token(token.strip())

    try:
        hotel_user_id = int(payload.get("hotel_user_id"))
    except (TypeError, ValueError):
        raise _unauthorized("Invalid token") from None

    user = db.get(HotelUser, hotel_user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User is inactive or no longer exists")
    if normalize_role(payload.get("role")) != normalize_role(user.role):
        # The signed claims no longer match the account (role changed, or a
        # forged claim). Force a fresh login rather than honouring either.
        raise _unauthorized("Token role does not match user account")
    return user


def require_roles(*roles: str | StaffRole) -> Callable[[HotelUser], HotelUser]:
    """Dependency factory: allow only the given staff roles (403 otherwise).

    Usage::

        @router.post("/hotel-users", ...)
        def create_hotel_user(
            ...,
            current_user: HotelUser = Depends(
                require_roles(StaffRole.HOTEL_ADMIN, StaffRole.SUPER_ADMIN)
            ),
        ): ...

    Unknown role strings on the user fail closed (403). Unauthenticated
    requests still get 401 from :func:`get_current_user` first.
    """
    allowed = {normalize_role(role) for role in roles} - {None}

    def _role_guard(current_user: HotelUser = Depends(get_current_user)) -> HotelUser:
        if normalize_role(current_user.role) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation",
            )
        return current_user

    return _role_guard
