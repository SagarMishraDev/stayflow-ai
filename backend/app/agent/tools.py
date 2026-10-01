import json
from datetime import date
from decimal import Decimal

from app.db.session import SessionLocal
from app.models import (
    FAQ,
    Availability,
    MenuItem,
    Offer,
    Policy,
    Rate,
    Room,
    Service,
)


def _serialize(value):
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, date):
        return value.isoformat()

    return value


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _success(data):
    return json.dumps(
        {
            "success": True,
            "data": data,
        },
        default=_serialize,
    )


def _error(message: str):
    return json.dumps(
        {
            "success": False,
            "error": message,
        }
    )


# ============================================================
# HOTEL INFORMATION
# ============================================================


def get_hotel_info(hotel_id: int) -> str:
    with SessionLocal() as db:
        hotel = db.get(
            __import__("app.models", fromlist=["Hotel"]).Hotel,
            hotel_id,
        )

        if not hotel or not hotel.is_active:
            return _error("Hotel information is currently unavailable.")

        return _success(
            {
                "id": hotel.id,
                "name": hotel.name,
                "description": hotel.description,
                "city": hotel.city,
                "address": hotel.address,
                "phone": hotel.phone,
                "email": hotel.email,
                "timezone": hotel.timezone,
                "currency": hotel.currency,
            }
        )


# ============================================================
# ROOMS
# ============================================================


def get_rooms(hotel_id: int) -> str:
    with SessionLocal() as db:
        rooms = (
            db.query(Room)
            .filter(
                Room.hotel_id == hotel_id,
                Room.is_active.is_(True),
            )
            .order_by(Room.room_type)
            .all()
        )

        if not rooms:
            return _error("No active rooms are currently available.")

        result = []

        for room in rooms:
            result.append(
                {
                    "id": room.id,
                    "room_type": room.room_type,
                    "description": room.description,
                    "capacity": room.capacity,
                    "total_rooms": room.total_rooms,
                    "amenities": room.amenities,
                }
            )

        return _success(result)


# ============================================================
# ROOM RATES
# ============================================================


def get_room_rates(
    hotel_id: int,
    room_type: str,
    check_in: str,
    check_out: str,
) -> str:
    try:
        start_date = _parse_date(check_in)
        end_date = _parse_date(check_out)
    except ValueError:
        return _error("Invalid date format. Please use YYYY-MM-DD.")

    if start_date >= end_date:
        return _error("Check-in date must be before check-out date.")

    with SessionLocal() as db:
        room = (
            db.query(Room)
            .filter(
                Room.hotel_id == hotel_id,
                Room.room_type.ilike(room_type),
                Room.is_active.is_(True),
            )
            .first()
        )

        if not room:
            return _error(f"Room type '{room_type}' was not found.")

        rates = (
            db.query(Rate)
            .filter(
                Rate.room_id == room.id,
                Rate.date >= start_date,
                Rate.date < end_date,
                Rate.is_active.is_(True),
            )
            .order_by(Rate.date)
            .all()
        )

        if not rates:
            return _error("No room rates are available for the requested dates.")

        result = [
            {
                "date": rate.date,
                "price": rate.price,
                "currency": rate.currency,
            }
            for rate in rates
        ]

        return _success(
            {
                "room_type": room.room_type,
                "check_in": start_date,
                "check_out": end_date,
                "rates": result,
            }
        )


# ============================================================
# AVAILABILITY
# ============================================================


def check_availability(
    hotel_id: int,
    room_type: str,
    check_in: str,
    check_out: str,
) -> str:
    try:
        start_date = _parse_date(check_in)
        end_date = _parse_date(check_out)
    except ValueError:
        return _error("Invalid date format. Please use YYYY-MM-DD.")

    if start_date >= end_date:
        return _error("Check-in date must be before check-out date.")

    with SessionLocal() as db:
        room = (
            db.query(Room)
            .filter(
                Room.hotel_id == hotel_id,
                Room.room_type.ilike(room_type),
                Room.is_active.is_(True),
            )
            .first()
        )

        if not room:
            return _error(f"Room type '{room_type}' was not found.")

        availability = (
            db.query(Availability)
            .filter(
                Availability.room_id == room.id,
                Availability.date >= start_date,
                Availability.date < end_date,
                Availability.is_active.is_(True),
            )
            .order_by(Availability.date)
            .all()
        )

        expected_days = (end_date - start_date).days

        if len(availability) != expected_days:
            return _error("Availability information is incomplete for the requested dates.")

        result = [
            {
                "date": item.date,
                "available_rooms": item.available_rooms,
            }
            for item in availability
        ]

        is_available = all(item.available_rooms > 0 for item in availability)

        minimum_available = min(item.available_rooms for item in availability)

        return _success(
            {
                "room_type": room.room_type,
                "check_in": start_date,
                "check_out": end_date,
                "available": is_available,
                "minimum_available_rooms": minimum_available,
                "daily_availability": result,
            }
        )


# ============================================================
# POLICIES
# ============================================================


def get_policies(
    hotel_id: int,
    policy_type: str | None = None,
) -> str:
    with SessionLocal() as db:
        query = db.query(Policy).filter(
            Policy.hotel_id == hotel_id,
            Policy.is_active.is_(True),
        )

        if policy_type:
            query = query.filter(Policy.policy_type.ilike(policy_type))

        policies = query.order_by(Policy.policy_type).all()

        if not policies:
            return _error("No active hotel policies are currently available.")

        result = [
            {
                "policy_type": policy.policy_type,
                "title": policy.title,
                "description": policy.description,
            }
            for policy in policies
        ]

        return _success(result)


# ============================================================
# FAQS
# ============================================================


def get_faqs(
    hotel_id: int,
    category: str | None = None,
) -> str:
    with SessionLocal() as db:
        query = db.query(FAQ).filter(
            FAQ.hotel_id == hotel_id,
            FAQ.is_active.is_(True),
        )

        if category:
            query = query.filter(FAQ.category.ilike(category))

        faqs = query.order_by(
            FAQ.category,
            FAQ.question,
        ).all()

        if not faqs:
            return _error("No active FAQs are currently available.")

        result = [
            {
                "question": faq.question,
                "answer": faq.answer,
                "category": faq.category,
            }
            for faq in faqs
        ]

        return _success(result)


# ============================================================
# SERVICES
# ============================================================


def get_services(hotel_id: int) -> str:
    with SessionLocal() as db:
        services = (
            db.query(Service)
            .filter(
                Service.hotel_id == hotel_id,
                Service.is_active.is_(True),
            )
            .order_by(Service.category, Service.name)
            .all()
        )

        if not services:
            return _error("No active hotel services are currently available.")

        result = [
            {
                "name": service.name,
                "description": service.description,
                "category": service.category,
                "price": service.price,
            }
            for service in services
        ]

        return _success(result)


# ============================================================
# MENU
# ============================================================


def get_menu(
    hotel_id: int,
    category: str | None = None,
) -> str:
    with SessionLocal() as db:
        query = db.query(MenuItem).filter(
            MenuItem.hotel_id == hotel_id,
            MenuItem.is_active.is_(True),
            MenuItem.is_available.is_(True),
        )

        if category:
            query = query.filter(MenuItem.category.ilike(category))

        items = query.order_by(
            MenuItem.category,
            MenuItem.name,
        ).all()

        if not items:
            if category:
                return _error(f"No available menu items were found for category '{category}'.")

            return _error("No available menu items are currently available.")

        result = [
            {
                "name": item.name,
                "description": item.description,
                "category": item.category,
                "price": item.price,
            }
            for item in items
        ]

        return _success(result)


# ============================================================
# OFFERS
# ============================================================


def get_offers(
    hotel_id: int,
    stay_date: str | None = None,
) -> str:
    parsed_date = None

    if stay_date:
        try:
            parsed_date = _parse_date(stay_date)
        except ValueError:
            return _error("Invalid stay date. Please use YYYY-MM-DD.")

    with SessionLocal() as db:
        query = db.query(Offer).filter(
            Offer.hotel_id == hotel_id,
            Offer.is_active.is_(True),
        )

        if parsed_date:
            query = query.filter(
                Offer.valid_from <= parsed_date,
                Offer.valid_until >= parsed_date,
            )

        offers = query.order_by(Offer.valid_from).all()

        if not offers:
            return _error("No active hotel offers are currently available.")

        result = [
            {
                "name": offer.name,
                "description": offer.description,
                "discount_type": offer.discount_type,
                "discount_value": offer.discount_value,
                "valid_from": offer.valid_from,
                "valid_until": offer.valid_until,
            }
            for offer in offers
        ]

        return _success(result)


# ============================================================
# TOOL DEFINITIONS
# ============================================================


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_hotel_info",
            "description": (
                "Get factual information about the hotel, "
                "including its name, description, location, "
                "contact information and currency."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rooms",
            "description": (
                "Get the active room types offered by the hotel, "
                "including capacity, description and amenities."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_room_rates",
            "description": (
                "Get date-wise room prices for a specific room type "
                "between check-in and check-out dates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_type": {
                        "type": "string",
                        "description": "The room type requested by the guest.",
                    },
                    "check_in": {
                        "type": "string",
                        "description": "Check-in date in YYYY-MM-DD format.",
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Check-out date in YYYY-MM-DD format.",
                    },
                },
                "required": [
                    "room_type",
                    "check_in",
                    "check_out",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check whether a specific room type is available for the requested date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_type": {
                        "type": "string",
                        "description": "The room type requested by the guest.",
                    },
                    "check_in": {
                        "type": "string",
                        "description": "Check-in date in YYYY-MM-DD format.",
                    },
                    "check_out": {
                        "type": "string",
                        "description": "Check-out date in YYYY-MM-DD format.",
                    },
                },
                "required": [
                    "room_type",
                    "check_in",
                    "check_out",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policies",
            "description": (
                "Get hotel policies such as check-in, check-out, "
                "cancellation, children, payment, smoking and extra-bed policies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_type": {
                        "type": "string",
                        "description": (
                            "Optional policy type such as check_in, "
                            "cancellation, children or payment."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_faqs",
            "description": ("Get frequently asked questions and answers about the hotel."),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional FAQ category such as Food, Facilities, Rooms or Transport."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_services",
            "description": (
                "Get active hotel services and their prices, "
                "such as airport transfer, laundry, room service "
                "and housekeeping."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_menu",
            "description": (
                "Get currently available food and beverage menu items "
                "from the hotel. Use this when the guest asks about "
                "breakfast, lunch, tea, coffee, evening snacks, dinner, "
                "desserts, beverages, vegetarian food or the restaurant menu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional menu category. Use one of: "
                            "Breakfast, Lunch, Tea & Coffee, "
                            "Evening Snacks, Dinner, Dessert, "
                            "or Beverages."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_offers",
            "description": (
                "Get current hotel offers and discounts. "
                "Never invent or calculate an offer that is not "
                "returned by this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stay_date": {
                        "type": "string",
                        "description": (
                            "Optional stay date in YYYY-MM-DD format. "
                            "Use it to find offers valid on a specific date."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


# ============================================================
# TOOL EXECUTOR
# ============================================================


def execute_tool(
    tool_name: str,
    arguments: dict,
) -> str:
    if tool_name == "get_hotel_info":
        return get_hotel_info(**arguments)

    if tool_name == "get_rooms":
        return get_rooms(**arguments)

    if tool_name == "get_room_rates":
        return get_room_rates(**arguments)

    if tool_name == "check_availability":
        return check_availability(**arguments)

    if tool_name == "get_policies":
        return get_policies(**arguments)

    if tool_name == "get_faqs":
        return get_faqs(**arguments)

    if tool_name == "get_services":
        return get_services(**arguments)

    if tool_name == "get_menu":
        return get_menu(**arguments)

    if tool_name == "get_offers":
        return get_offers(**arguments)

    return _error(f"Unknown tool: {tool_name}")
