"""Hospitality operations tools (Phase 5 of the agent layer)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.tools.registry import ToolContext, ToolSpec
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.service import Service
from app.models.service_request import ServiceRequest
from app.services.audit import log_action


def _require_hotel(db: Session, hotel_id: int) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise ValueError(f"Hotel {hotel_id} not found")
    return hotel


def _resolve_guest(db: Session, hotel_id: int, guest_id: int | None, ctx: ToolContext) -> Guest:
    resolved = guest_id or ctx.guest_id
    if resolved is None:
        raise ValueError("No guest identified. Use find_or_create_guest first.")
    guest = db.get(Guest, resolved)
    if guest is None or guest.hotel_id != hotel_id:
        raise ValueError("Guest not found for this hotel")
    return guest


# --------------------------------------------------------------------- #
# get_menu                                                               #
# --------------------------------------------------------------------- #
class GetMenuArgs(BaseModel):
    hotel_id: int
    category: str | None = Field(default=None, description="Filter by category")


def get_menu(db: Session, ctx: ToolContext, args: GetMenuArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    stmt = select(MenuItem).where(
        MenuItem.hotel_id == args.hotel_id,
        MenuItem.is_active.is_(True),
        MenuItem.is_available.is_(True),
    )
    if args.category:
        stmt = stmt.where(func.lower(MenuItem.category) == args.category.lower())
    items = db.scalars(stmt.order_by(MenuItem.id)).all()
    return {
        "items": [
            {
                "menu_item_id": i.id,
                "name": i.name,
                "description": i.description,
                "category": i.category,
                "price": str(i.price),
            }
            for i in items
        ]
    }


# --------------------------------------------------------------------- #
# create_food_order                                                      #
# --------------------------------------------------------------------- #
class OrderLineArgs(BaseModel):
    menu_item_id: int | None = Field(default=None)
    menu_item_name: str | None = Field(default=None)
    quantity: int = Field(gt=0, le=20)
    customization: str | None = None


class CreateFoodOrderArgs(BaseModel):
    hotel_id: int
    guest_id: int | None = None
    order_type: str = Field(description="DINE_IN, ROOM_SERVICE or TAKEAWAY")
    items: list[OrderLineArgs] = Field(min_length=1, max_length=20)
    room_number: str | None = None
    table_number: int | None = None


def create_food_order(db: Session, ctx: ToolContext, args: CreateFoodOrderArgs) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    guest = _resolve_guest(db, args.hotel_id, args.guest_id, ctx)
    order_type = args.order_type.upper()
    if order_type not in ("DINE_IN", "ROOM_SERVICE", "TAKEAWAY"):
        raise ValueError("order_type must be DINE_IN, ROOM_SERVICE or TAKEAWAY")

    order = Order(
        hotel_id=args.hotel_id,
        guest_id=guest.id,
        order_type=order_type,
        table_number=args.table_number,
        status="CONFIRMED",
    )
    db.add(order)
    db.flush()

    total = Decimal("0.00")
    lines: list[dict[str, Any]] = []
    for line in args.items:
        menu_item: MenuItem | None = None
        if line.menu_item_id is not None:
            menu_item = db.get(MenuItem, line.menu_item_id)
        elif line.menu_item_name:
            menu_item = db.scalar(
                select(MenuItem).where(
                    MenuItem.hotel_id == args.hotel_id,
                    func.lower(MenuItem.name) == line.menu_item_name.lower(),
                )
            )
        if menu_item is None or menu_item.hotel_id != args.hotel_id:
            raise ValueError(f"Menu item not found: {line.menu_item_id or line.menu_item_name}")
        if not menu_item.is_active or not menu_item.is_available:
            raise ValueError(f"Menu item '{menu_item.name}' is not available")
        # Trusted pricing: always the database price, never a client/LLM price.
        subtotal = menu_item.price * line.quantity
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                quantity=line.quantity,
                unit_price=menu_item.price,
                customization=line.customization,
                subtotal=subtotal,
            )
        )
        total += subtotal
        lines.append(
            {
                "name": menu_item.name,
                "quantity": line.quantity,
                "unit_price": str(menu_item.price),
                "subtotal": str(subtotal),
            }
        )

    order.total_amount = total
    db.flush()
    # Kitchen queue notification (role-addressed; operational facts only).
    from app.services.notifications import notify_role

    notify_role(
        db,
        hotel_id=args.hotel_id,
        target_role="kitchen",
        type="order.new",
        title="New food order",
        message=f"New {order_type} order #{order.id} ({len(lines)} item lines).",
        reference_type="order",
        reference_id=order.id,
    )
    log_action(
        db,
        hotel_id=args.hotel_id,
        actor_type=ctx.actor_type,
        actor_id=guest.id,
        action="order.created",
        entity_type="order",
        entity_id=order.id,
        details={"order_type": order_type, "total": str(total)},
    )
    db.commit()
    return {
        "order_id": order.id,
        "order_type": order_type,
        "status": order.status,
        "total_amount": str(total),
        "items": lines,
    }


# --------------------------------------------------------------------- #
# create_service_request                                                 #
# --------------------------------------------------------------------- #
class CreateServiceRequestArgs(BaseModel):
    hotel_id: int
    guest_id: int | None = None
    service_id: int | None = None
    service_name: str | None = None
    room_number: str | None = None
    request_text: str | None = None


def create_service_request(
    db: Session, ctx: ToolContext, args: CreateServiceRequestArgs
) -> dict[str, Any]:
    _require_hotel(db, args.hotel_id)
    guest = _resolve_guest(db, args.hotel_id, args.guest_id, ctx)

    service: Service | None = None
    if args.service_id is not None:
        service = db.get(Service, args.service_id)
    elif args.service_name:
        service = db.scalar(
            select(Service).where(
                Service.hotel_id == args.hotel_id,
                func.lower(Service.name).contains(args.service_name.lower()),
                Service.is_active.is_(True),
            )
        )
    if service is None or service.hotel_id != args.hotel_id:
        raise ValueError("Service not found for this hotel")

    request = ServiceRequest(
        hotel_id=args.hotel_id,
        guest_id=guest.id,
        service_id=service.id,
        room_number=args.room_number,
        request_text=args.request_text,
        status="PENDING",
    )
    db.add(request)
    db.flush()
    log_action(
        db,
        hotel_id=args.hotel_id,
        actor_type=ctx.actor_type,
        actor_id=guest.id,
        action="service_request.created",
        entity_type="service_request",
        entity_id=request.id,
        details={"service": service.name},
    )
    db.commit()
    return {
        "service_request_id": request.id,
        "service_name": service.name,
        "status": request.status,
    }


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_menu",
        description="List available food menu items with trusted prices.",
        args_model=GetMenuArgs,
        handler=get_menu,
        read_only=True,
    ),
    ToolSpec(
        name="create_food_order",
        description=(
            "Create a food order. Prices are always taken from the menu — "
            "never invent or accept prices."
        ),
        args_model=CreateFoodOrderArgs,
        handler=create_food_order,
        read_only=False,
    ),
    ToolSpec(
        name="create_service_request",
        description=("Raise a service request (housekeeping, maintenance, transport, ...)."),
        args_model=CreateServiceRequestArgs,
        handler=create_service_request,
        read_only=False,
    ),
]

__all__ = ["SPECS"]
