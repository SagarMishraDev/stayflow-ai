"""Staff role model for StayFlow RBAC (Prompt-2 section 23).

Roles, from most to least privileged:

- ``SUPER_ADMIN`` — platform operator. May access data of *any* hotel;
  every cross-hotel access is written to the audit log (and logged at
  WARNING level) so the bypass stays visible.
- ``HOTEL_ADMIN`` — manages one hotel: its staff users, inventory, rates,
  content and operations.
- ``STAFF`` — day-to-day operations for one hotel (bookings, orders,
  service requests, ...). Cannot manage staff users.

Role checks are done by ``require_roles`` in :mod:`app.core.security`,
built on top of ``get_current_user``. The role string stored on
``HotelUser`` is authoritative; the JWT ``role`` claim is cross-checked
against it at authentication time, so a forged claim in a hand-crafted
token is rejected instead of granting extra rights.

Legacy note: pre-RBAC installs stored ``"admin"`` in the role column.
``normalize_role`` maps that alias to ``HOTEL_ADMIN`` so existing staff
keep working without a data migration.
"""

from __future__ import annotations

from enum import StrEnum


class StaffRole(StrEnum):
    """The three staff roles recognised by StayFlow."""

    SUPER_ADMIN = "super_admin"
    HOTEL_ADMIN = "hotel_admin"
    STAFF = "staff"


# Convenience aliases so call sites read naturally: ``require_roles(HOTEL_ADMIN)``.
SUPER_ADMIN = StaffRole.SUPER_ADMIN
HOTEL_ADMIN = StaffRole.HOTEL_ADMIN
STAFF = StaffRole.STAFF

# Historical role strings accepted at the boundary (see module docstring).
_ROLE_ALIASES: dict[str, StaffRole] = {
    "admin": StaffRole.HOTEL_ADMIN,
}


def normalize_role(value: str | StaffRole | None) -> StaffRole | None:
    """Map a raw role value to a :class:`StaffRole`, or ``None`` if unknown.

    Unknown values fail closed: callers must treat ``None`` as "no
    permissions" rather than defaulting to a role.
    """
    if isinstance(value, StaffRole):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    for role in StaffRole:
        if role.value == cleaned:
            return role
    return _ROLE_ALIASES.get(cleaned)


def is_super_admin(value: str | StaffRole | None) -> bool:
    """True when the value is the super-admin role (legacy aliases excluded)."""
    return normalize_role(value) is StaffRole.SUPER_ADMIN
