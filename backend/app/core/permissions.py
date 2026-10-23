"""Capability permission matrix — single source of truth (HMS Phase 3).

Every fine-grained authorisation decision in the API should go through
this module: endpoints declare the *capability* they need
(``require_permission("bookings.manage")``) and the matrix below decides
which roles hold it.  The frontend mirrors this matrix in
``frontend/dashboard/src/lib/roles.ts`` for UI hiding only — the backend
is authoritative.

Fail-closed rules:
- Unknown roles hold no capabilities.
- Unknown capabilities are held by nobody (not even SUPER_ADMIN).
- ``SUPER_ADMIN`` holds every *known* capability.
- Nobody can create a ``SUPER_ADMIN`` via the API; that rule lives in
  the staff-management endpoints, not in this matrix.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.core.roles import StaffRole, normalize_role

# Shorthands for the matrix below.
_SA = StaffRole.SUPER_ADMIN
_HA = StaffRole.HOTEL_ADMIN
_MGR = StaffRole.MANAGER
_STF = StaffRole.STAFF
_REC = StaffRole.RECEPTIONIST
_KIT = StaffRole.KITCHEN
_HK = StaffRole.HOUSEKEEPING
_ACC = StaffRole.ACCOUNTANT
_MNT = StaffRole.MAINTENANCE

_ALL_ROLES: frozenset[StaffRole] = frozenset(StaffRole)

#: Capability string -> roles that hold it. SUPER_ADMIN is included
#: explicitly in every row (and also short-circuited in has_permission).
PERMISSIONS: dict[str, frozenset[StaffRole]] = {
    "analytics.view": frozenset({_SA, _HA, _MGR, _ACC}),
    "analytics.finance": frozenset({_SA, _HA, _ACC}),
    "bookings.view": frozenset({_SA, _HA, _MGR, _STF, _REC, _ACC, _HK}),
    "bookings.manage": frozenset({_SA, _HA, _MGR, _STF, _REC}),
    "checkin.manage": frozenset({_SA, _HA, _MGR, _STF, _REC}),
    "rooms.view": _ALL_ROLES,
    "rooms.manage": frozenset({_SA, _HA, _MGR, _STF}),
    "orders.view": frozenset({_SA, _HA, _MGR, _STF, _REC, _KIT}),
    "orders.manage": frozenset({_SA, _HA, _MGR, _STF, _REC}),
    "orders.kitchen": frozenset({_SA, _HA, _MGR, _STF, _KIT}),
    "service_requests.view": frozenset({_SA, _HA, _MGR, _STF, _REC, _HK, _MNT}),
    "service_requests.manage": frozenset({_SA, _HA, _MGR, _STF, _REC, _HK, _MNT}),
    "housekeeping.manage": frozenset({_SA, _HA, _MGR, _HK}),
    "maintenance.manage": frozenset({_SA, _HA, _MGR, _MNT}),
    "menu.manage": frozenset({_SA, _HA, _MGR, _KIT}),
    "payments.view": frozenset({_SA, _HA, _MGR, _STF, _REC, _ACC}),
    "payments.record": frozenset({_SA, _HA, _MGR, _STF, _REC, _ACC}),
    # Any authenticated staff member may view the staff directory
    # (preserves the pre-Phase-3 behaviour relied on by the dashboard
    # and tests); creating/managing accounts is restricted below.
    "staff.view": _ALL_ROLES,
    # Admin only: only HOTEL_ADMIN / SUPER_ADMIN may create a MANAGER
    # (or another HOTEL_ADMIN). SUPER_ADMIN creation is never allowed
    # via the API at all.
    "staff.create_manager": frozenset({_SA, _HA}),
    "staff.create_staff": frozenset({_SA, _HA, _MGR}),
    "staff.manage": frozenset({_SA, _HA, _MGR}),
    "settings.manage": frozenset({_SA, _HA}),
    # Manager gets limited operational logs; accountant gets finance-
    # relevant logs. Receptionist/kitchen/housekeeping/maintenance do not.
    "audit.view": frozenset({_SA, _HA, _MGR, _ACC}),
    "notifications.view": _ALL_ROLES,
}

#: Roles a MANAGER may create (and may update/deactivate). Managers may
#: never create or promote anyone to HOTEL_ADMIN / MANAGER / SUPER_ADMIN.
MANAGER_CREATABLE_ROLES: frozenset[StaffRole] = frozenset({_REC, _KIT, _HK, _ACC, _MNT, _STF})

#: Roles that may manage staff accounts at all (subject to the
#: per-target rules enforced in the staff endpoints).
STAFF_MANAGERS: frozenset[StaffRole] = frozenset({_SA, _HA, _MGR})


def has_permission(role: str | StaffRole | None, capability: str) -> bool:
    """True when ``role`` holds ``capability``. Unknown -> False."""
    normalized = normalize_role(role)
    if normalized is None:
        return False
    allowed = PERMISSIONS.get(capability)
    if allowed is None:
        return False
    if normalized is StaffRole.SUPER_ADMIN:
        return True
    return normalized in allowed


def require_permission(capability: str) -> Callable:
    """FastAPI dependency factory: 403 unless the user holds ``capability``.

    Usage::

        current_user: HotelUser = Depends(require_permission("audit.view"))

    Unauthenticated requests still get 401 from ``get_current_user``.
    Imported lazily inside the factory to avoid a circular import with
    :mod:`app.core.security` (which does not import this module).
    """
    from app.core.security import get_current_user
    from app.models.hotel_user import HotelUser

    def _permission_guard(
        current_user: HotelUser = Depends(get_current_user),
    ) -> HotelUser:
        if not has_permission(current_user.role, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permission: {capability} required",
            )
        return current_user

    return _permission_guard


def require_any_permission(*capabilities: str) -> Callable:
    """Dependency factory: allow when the user holds ANY listed capability."""
    from app.core.security import get_current_user
    from app.models.hotel_user import HotelUser

    def _any_guard(
        current_user: HotelUser = Depends(get_current_user),
    ) -> HotelUser:
        if not any(has_permission(current_user.role, cap) for cap in capabilities):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permission: one of {', '.join(capabilities)} required",
            )
        return current_user

    return _any_guard
