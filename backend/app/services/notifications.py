"""Role-targeted operational notifications (HMS upgrade Phase 5).

Notifications live in the existing ``notifications`` table. A row is
addressed either to one staff user (``user_id``) or to a role queue
(``target_role``) — e.g. every KITCHEN user sees new food orders.
Payloads contain operational facts only (ids, room numbers, statuses);
payment details and guest contact data are never copied into a
notification that a broad role queue can read.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.notification import Notification


def notify_role(
    db: Session,
    *,
    hotel_id: int,
    target_role: str,
    type: str,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> Notification:
    row = Notification(
        hotel_id=hotel_id,
        user_id=None,
        target_role=target_role,
        type=type,
        title=title,
        message=message,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(row)
    db.flush()
    return row


def notify_user(
    db: Session,
    *,
    hotel_id: int,
    user_id: int,
    type: str,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> Notification:
    row = Notification(
        hotel_id=hotel_id,
        user_id=user_id,
        target_role=None,
        type=type,
        title=title,
        message=message,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(row)
    db.flush()
    return row
