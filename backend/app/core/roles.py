"""Staff role model for StayFlow RBAC (Prompt-2 section 23, HMS Phase 3).

Roles, from most to least privileged:

- ``SUPER_ADMIN`` — platform operator. May access data of *any* hotel;
  every cross-hotel access is written to the audit log (and logged at
  WARNING level) so the bypass stays visible.
- ``HOTEL_ADMIN`` — Admin/Owner of one hotel: manages its staff users,
  inventory, rates, content, finance and operations. Has every
  capability except creating a ``SUPER_ADMIN`` (nobody can via the API).
- ``MANAGER`` — hotel manager: broad operational access, analytics and
  limited operational logs, and may create/manage only operational
  staff (receptionist, kitchen, housekeeping, accountant, maintenance
  and generic staff) — never admins, managers or super admins.
- ``STAFF`` — generic staff: day-to-day operations for one hotel
  (bookings, orders, service requests, ...), treated as
  receptionist-level operations access where sensible. Cannot manage
  staff users.
- ``RECEPTIONIST`` — front desk: bookings, check-in, guests, orders.
- ``KITCHEN`` — kitchen staff: food orders (kitchen view) and menu.
- ``HOUSEKEEPING`` — housekeeping: service requests and room status.
- ``ACCOUNTANT`` — finance: payments, finance analytics and audit logs.
- ``MAINTENANCE`` — maintenance: service requests / maintenance work.

Capability checks live in :mod:`app.core.permissions` (the single
source of truth mapping capabilities to roles); ``require_roles`` in
:mod:`app.core.security` remains for coarse role gates. The role
string stored on ``HotelUser`` is authoritative; the JWT ``role``
claim is cross-checked against it at authentication time, so a forged
claim in a hand-crafted token is rejected instead of granting extra
rights.

Legacy note: pre-RBAC installs stored ``"admin"`` in the role column.
``normalize_role`` maps that alias to ``HOTEL_ADMIN`` so existing staff
keep working without a data migration.
"""

from __future__ import annotations

from enum import StrEnum


class StaffRole(StrEnum):
    """The staff roles recognised by StayFlow (HMS Phase 3)."""

    SUPER_ADMIN = "super_admin"
    HOTEL_ADMIN = "hotel_admin"
    STAFF = "staff"
    MANAGER = "manager"
    RECEPTIONIST = "receptionist"
    KITCHEN = "kitchen"
    HOUSEKEEPING = "housekeeping"
    ACCOUNTANT = "accountant"
    MAINTENANCE = "maintenance"


# Convenience aliases so call sites read naturally: ``require_roles(HOTEL_ADMIN)``.
SUPER_ADMIN = StaffRole.SUPER_ADMIN
HOTEL_ADMIN = StaffRole.HOTEL_ADMIN
STAFF = StaffRole.STAFF
MANAGER = StaffRole.MANAGER
RECEPTIONIST = StaffRole.RECEPTIONIST
KITCHEN = StaffRole.KITCHEN
HOUSEKEEPING = StaffRole.HOUSEKEEPING
ACCOUNTANT = StaffRole.ACCOUNTANT
MAINTENANCE = StaffRole.MAINTENANCE

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
