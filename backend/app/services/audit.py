"""Audit-log helper used by services and routers.

Audit logs record *actions* (what happened, who did it). They never store
hidden model reasoning or raw LLM prompts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    *,
    hotel_id: int,
    actor_type: str,
    action: str,
    actor_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | str | None = None,
) -> AuditLog:
    """Persist an audit-log row. The caller owns the surrounding transaction."""
    if isinstance(details, dict):
        details_text: str | None = json.dumps(details, default=str)
    else:
        details_text = details

    entry = AuditLog(
        hotel_id=hotel_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details_text,
    )
    db.add(entry)
    return entry


def log_super_admin_cross_hotel_access(
    *,
    actor_id: int,
    actor_hotel_id: int,
    accessed_hotel_id: int,
    resource: str,
) -> None:
    """Record a SUPER_ADMIN tenant-boundary crossing, prominently.

    Super admins bypass hotel tenant isolation, so every cross-hotel access
    is written to the audit log *and* emitted at WARNING level on the
    application log. Uses its own database session because the bypass often
    happens inside read-only requests that never commit.
    """
    from app.db.session import SessionLocal

    details = json.dumps(
        {
            "actor_role": "super_admin",
            "actor_hotel_id": actor_hotel_id,
            "accessed_hotel_id": accessed_hotel_id,
            "resource": resource,
        }
    )
    logger.warning(
        "SUPER_ADMIN cross-hotel access: staff user %s (hotel %s) accessed %s of hotel %s",
        actor_id,
        actor_hotel_id,
        resource,
        accessed_hotel_id,
    )
    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                hotel_id=accessed_hotel_id,
                actor_type="staff",
                actor_id=actor_id,
                action="super_admin.cross_hotel_access",
                entity_type="hotel",
                entity_id=accessed_hotel_id,
                details=details,
            )
        )
        db.commit()
    finally:
        db.close()
