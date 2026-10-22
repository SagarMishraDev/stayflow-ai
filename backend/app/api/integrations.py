"""Server-to-server integration API + staff integration settings (§12).

Chat endpoint: ``POST /api/v1/integrations/chat/message``

Lets a hotel's existing website chat (or any partner backend) send a
guest message to the StayFlow agent and receive a structured JSON reply,
without replacing its frontend. Full protocol docs: docs/INTEGRATIONS.md.

Security model:

- Authenticated per hotel by HMAC-SHA256 signature over
  ``timestamp + "." + raw_body`` (headers ``X-StayFlow-Timestamp`` /
  ``X-StayFlow-Signature``), verified in constant time against the
  hotel's integration secret (or the global fallback secret when the
  hotel has none). No staff JWT is accepted here, and no integration
  secret ever authenticates staff routes.
- Timestamps outside the configured window (default 5 min) are rejected;
  each accepted signature is recorded as a one-time nonce, so a captured
  request cannot be replayed inside the window. Requests carrying an
  idempotency key skip the nonce check — their duplicate handling is the
  idempotency store below (partners legitimately re-sign retries, and a
  byte-identical retry is answered from the stored response).
- ``Idempotency-Key`` header (or ``event_id`` in the body): duplicate
  deliveries return the original response without re-running the agent
  or duplicating conversation messages. Keys are hotel-scoped.
- Errors are structured ``{"error": {"code", "message"}}`` responses
  that never leak secrets, signatures, or infrastructure details.
- A minimal request log (hotel, outcome, ids) is kept in
  ``integration_request_logs`` — no secrets, signatures, or message text.

Staff endpoints (JWT-protected, hotel-scoped) manage the configuration:
view status, rotate secrets (the new secret is returned exactly once),
and set the outbound webhook URL. When a webhook URL + signing secret
are configured, each chat response is also delivered there as a signed
POST (best-effort, bounded retries — see app/services/webhook_delivery).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.config import AgentConfig
from app.agent.runner import run_chat
from app.api.public import get_hotel_by_public_id
from app.core.config import get_settings
from app.core.rate_limit import rate_limit_integration
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.hotel import Hotel
from app.models.hotel_user import HotelUser
from app.models.integration import IntegrationIdempotencyKey, IntegrationRequestLog
from app.models.integration_nonce import IntegrationNonce
from app.services.integration_security import (
    generate_secret,
    secret_fingerprint,
    verify_signature,
)
from app.services.webhook_delivery import deliver_webhook

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["integrations"])


# --------------------------------------------------------------------- #
# Schemas                                                                #
# --------------------------------------------------------------------- #
class IntegrationChatRequest(BaseModel):
    hotel_public_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    # Partner-side session identifier. When it is one of our conversation
    # ids (returned by a previous response, as a string) the conversation
    # continues; anything else starts a fresh conversation.
    session_id: str | None = None
    # Optional guest linkage: a StayFlow guest id for this hotel, and/or
    # the partner's own opaque reference (echoed back, never used as an
    # identity or a lookup key).
    guest_id: int | None = None
    guest_reference: str | None = Field(default=None, max_length=255)
    # Fallback idempotency key when the Idempotency-Key header is absent.
    event_id: str | None = Field(default=None, max_length=255)


class IntegrationChatResponse(BaseModel):
    conversation_id: int
    reply: str
    hotel_id: str  # the hotel public_id — never the internal integer id
    status: str = "ok"
    degraded: bool = False
    guest_reference: str | None = None


class IntegrationSettingsResponse(BaseModel):
    hotel_id: int
    public_id: str
    has_integration_secret: bool
    integration_secret_fingerprint: str | None
    integration_configured: bool
    integration_webhook_url: str | None
    has_webhook_secret: bool
    widget_base_url: str


class SecretRotateResponse(BaseModel):
    # Returned exactly once, in this response only. Store it in the
    # partner system's secret manager; it cannot be retrieved again.
    integration_secret: str
    integration_secret_fingerprint: str


class WebhookSecretRotateResponse(BaseModel):
    integration_webhook_secret: str


class WebhookUpdateRequest(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #
def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


def _write_log(
    db: Session,
    *,
    hotel_id: int,
    status_code: int,
    idempotency_key: str | None = None,
    conversation_id: int | None = None,
    error_code: str | None = None,
    webhook_delivered: bool | None = None,
) -> None:
    """Best-effort minimal request log (ids + outcome only)."""
    try:
        db.add(
            IntegrationRequestLog(
                hotel_id=hotel_id,
                idempotency_key=idempotency_key,
                conversation_id=conversation_id,
                status_code=status_code,
                error_code=error_code,
                webhook_delivered=webhook_delivered,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - logging must never fail a request
        db.rollback()
        logger.warning("integration request log write failed for hotel %s", hotel_id)


def _resolve_secret(hotel: Hotel) -> str | None:
    return hotel.integration_secret or settings.integration_fallback_secret


def _verify_request_signature(hotel: Hotel, request: Request, raw_body: bytes) -> str | None:
    """Return an error code when authentication fails, else None."""
    timestamp = request.headers.get("x-stayflow-timestamp")
    signature = request.headers.get("x-stayflow-signature")
    if not timestamp or not signature:
        return "missing_signature_headers"
    try:
        ts_value = int(timestamp)
    except ValueError:
        return "invalid_timestamp"
    window = settings.integration_timestamp_window_seconds
    if abs(int(time.time()) - ts_value) > window:
        return "timestamp_expired"
    secret = _resolve_secret(hotel)
    if not secret:
        return "integration_not_configured"
    if not verify_signature(secret, timestamp, raw_body, signature):
        return "invalid_signature"
    return None


def _check_replay(db: Session, hotel_id: int, signature: str) -> bool:
    """Record the signature as a nonce. True when it is a replay."""
    window = settings.integration_timestamp_window_seconds
    cutoff = datetime.now(UTC) - timedelta(seconds=window)
    # Opportunistic prune: expired nonces can never validate again because
    # their timestamps fall outside the window.
    db.query(IntegrationNonce).filter(IntegrationNonce.created_at < cutoff).delete(
        synchronize_session=False
    )
    db.add(IntegrationNonce(hotel_id=hotel_id, signature=signature.strip().lower()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return True
    return False


# --------------------------------------------------------------------- #
# Chat endpoint (server-to-server, HMAC-authenticated)                   #
# --------------------------------------------------------------------- #
@router.post(
    "/integrations/chat/message",
    responses={
        401: {"description": "Missing/invalid/expired signature or replayed request"},
        404: {"description": "Unknown hotel public_id"},
        429: {"description": "Rate limit exceeded — retry after the Retry-After delay"},
    },
)
async def integration_chat_message(
    request: Request,
    db: Session = Depends(get_db, scope="function"),
    _: None = Depends(rate_limit_integration),
) -> JSONResponse:
    raw_body = await request.body()
    try:
        data = json.loads(raw_body) if raw_body else {}
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
    except ValueError:
        raise _error(422, "invalid_json", "Request body must be a JSON object") from None
    try:
        payload = IntegrationChatRequest.model_validate(data)
    except ValidationError:
        raise _error(422, "validation_error", "Request body failed validation") from None

    try:
        hotel = get_hotel_by_public_id(db, payload.hotel_public_id)
    except HTTPException:
        raise _error(404, "hotel_not_found", "Hotel not found") from None

    idempotency_key = request.headers.get("idempotency-key") or payload.event_id

    auth_error = _verify_request_signature(hotel, request, raw_body)
    if auth_error is not None:
        _write_log(db, hotel_id=hotel.id, status_code=401, error_code=auth_error)
        raise _error(401, auth_error, "Request authentication failed")

    signature = request.headers.get("x-stayflow-signature", "")
    if not idempotency_key and _check_replay(db, hotel.id, signature):
        _write_log(
            db,
            hotel_id=hotel.id,
            status_code=401,
            error_code="replay_detected",
        )
        raise _error(401, "replay_detected", "This request has already been processed")

    if idempotency_key:
        existing = db.scalars(
            select(IntegrationIdempotencyKey).where(
                IntegrationIdempotencyKey.hotel_id == hotel.id,
                IntegrationIdempotencyKey.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            _write_log(
                db,
                hotel_id=hotel.id,
                status_code=existing.response_status,
                idempotency_key=idempotency_key,
                conversation_id=existing.conversation_id,
                error_code="idempotent_replay",
            )
            return JSONResponse(
                content=json.loads(existing.response_body),
                status_code=existing.response_status,
            )

    conversation_id = payload.conversation_id
    if conversation_id is None and payload.session_id:
        try:
            conversation_id = int(payload.session_id)
        except ValueError:
            conversation_id = None

    try:
        result = run_chat(
            db,
            hotel_id=hotel.id,
            message=payload.message,
            conversation_id=conversation_id,
            guest_id=payload.guest_id,
            channel="integration",
            config=AgentConfig.from_settings(settings),
        )
    except ValueError as exc:
        _write_log(
            db,
            hotel_id=hotel.id,
            status_code=422,
            idempotency_key=idempotency_key,
            error_code="agent_validation_error",
        )
        raise _error(422, "agent_validation_error", str(exc)) from exc
    except Exception:  # noqa: BLE001 - safe error, details stay in server logs
        logger.exception("integration chat failed for hotel %s", hotel.id)
        _write_log(
            db,
            hotel_id=hotel.id,
            status_code=500,
            idempotency_key=idempotency_key,
            error_code="agent_error",
        )
        raise _error(500, "agent_error", "The agent could not process this message") from None

    response_payload = IntegrationChatResponse(
        conversation_id=result.conversation_id,
        reply=result.reply,
        hotel_id=hotel.public_id,
        degraded=result.degraded,
        guest_reference=payload.guest_reference,
    ).model_dump()

    if idempotency_key:
        record = IntegrationIdempotencyKey(
            hotel_id=hotel.id,
            idempotency_key=idempotency_key,
            conversation_id=result.conversation_id,
            response_status=200,
            response_body=json.dumps(response_payload),
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent duplicate won the race: answer with its stored
            # response instead of the one we just computed.
            db.rollback()
            winner = db.scalars(
                select(IntegrationIdempotencyKey).where(
                    IntegrationIdempotencyKey.hotel_id == hotel.id,
                    IntegrationIdempotencyKey.idempotency_key == idempotency_key,
                )
            ).first()
            if winner is not None:
                return JSONResponse(
                    content=json.loads(winner.response_body),
                    status_code=winner.response_status,
                )
            raise _error(500, "idempotency_error", "Could not record the response") from None

    webhook_delivered: bool | None = None
    if hotel.integration_webhook_url and hotel.integration_webhook_secret:
        try:
            webhook_delivered = deliver_webhook(
                hotel.integration_webhook_url,
                response_payload,
                hotel.integration_webhook_secret,
                timeout_seconds=settings.integration_http_timeout_seconds,
                max_retries=settings.integration_max_retries,
            )
        except Exception:  # noqa: BLE001 - delivery must never fail the chat
            logger.exception("webhook delivery raised for hotel %s", hotel.id)
            webhook_delivered = False

    _write_log(
        db,
        hotel_id=hotel.id,
        status_code=200,
        idempotency_key=idempotency_key,
        conversation_id=result.conversation_id,
        webhook_delivered=webhook_delivered,
    )
    # Metadata only: never log the guest's message or the reply (PII).
    logger.info(
        "integration.chat hotel=%s conversation=%s degraded=%s webhook=%s",
        hotel.id,
        result.conversation_id,
        result.degraded,
        webhook_delivered,
    )
    return JSONResponse(content=response_payload, status_code=200)


# --------------------------------------------------------------------- #
# Staff settings endpoints (JWT-protected, hotel-scoped)                 #
# --------------------------------------------------------------------- #
def _staff_hotel(db: Session, current_user: HotelUser) -> Hotel:
    hotel = db.get(Hotel, current_user.hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return hotel


@router.get("/integrations/settings", response_model=IntegrationSettingsResponse)
def get_integration_settings(
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> IntegrationSettingsResponse:
    hotel = _staff_hotel(db, current_user)
    return IntegrationSettingsResponse(
        hotel_id=hotel.id,
        public_id=hotel.public_id,
        has_integration_secret=bool(hotel.integration_secret),
        integration_secret_fingerprint=hotel.integration_secret_fingerprint,
        integration_configured=bool(_resolve_secret(hotel)),
        integration_webhook_url=hotel.integration_webhook_url,
        has_webhook_secret=bool(hotel.integration_webhook_secret),
        widget_base_url=settings.widget_base_url,
    )


@router.post("/integrations/secret/rotate", response_model=SecretRotateResponse)
def rotate_integration_secret(
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> SecretRotateResponse:
    """Generate a new per-hotel integration secret (returned exactly once).

    The previous secret stops working immediately. The value is never
    logged and cannot be retrieved again — only its fingerprint is kept
    for identification.
    """
    hotel = _staff_hotel(db, current_user)
    secret = generate_secret()
    hotel.integration_secret = secret
    hotel.integration_secret_fingerprint = secret_fingerprint(secret)
    db.commit()
    logger.info("integration secret rotated for hotel %s by staff %s", hotel.id, current_user.id)
    return SecretRotateResponse(
        integration_secret=secret,
        integration_secret_fingerprint=hotel.integration_secret_fingerprint,
    )


@router.post("/integrations/webhook-secret/rotate", response_model=WebhookSecretRotateResponse)
def rotate_webhook_secret(
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> WebhookSecretRotateResponse:
    """Generate a new outbound-webhook signing secret (returned once)."""
    hotel = _staff_hotel(db, current_user)
    secret = generate_secret()
    hotel.integration_webhook_secret = secret
    db.commit()
    logger.info("webhook secret rotated for hotel %s by staff %s", hotel.id, current_user.id)
    return WebhookSecretRotateResponse(integration_webhook_secret=secret)


@router.patch("/integrations/webhook", response_model=IntegrationSettingsResponse)
def update_webhook(
    payload: WebhookUpdateRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> IntegrationSettingsResponse:
    hotel = _staff_hotel(db, current_user)
    url = payload.webhook_url.strip() if payload.webhook_url else None
    if url is not None and not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(
            status_code=422, detail="webhook_url must start with http:// or https://"
        )
    hotel.integration_webhook_url = url
    db.commit()
    logger.info(
        "integration webhook url updated for hotel %s by staff %s", hotel.id, current_user.id
    )
    return get_integration_settings(db=db, current_user=current_user)
