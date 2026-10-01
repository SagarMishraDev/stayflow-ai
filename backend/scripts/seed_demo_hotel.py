from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    FAQ,
    Availability,
    Hotel,
    MenuItem,
    Offer,
    Policy,
    Rate,
    Room,
    Service,
)

HOTEL_ID = 2

START_DATE = date(2026, 9, 21)
END_DATE = date(2026, 10, 31)


ROOMS = [
    {
        "room_type": "Executive Room",
        "description": "Comfortable premium room for business and leisure stays.",
        "capacity": 3,
        "total_rooms": 12,
        "amenities": "WiFi, AC, Smart TV, Breakfast, Work Desk, Electric Kettle",
    },
    {
        "room_type": "Deluxe Premium Room",
        "description": "Spacious city-view room with modern interiors and premium amenities.",
        "capacity": 4,
        "total_rooms": 10,
        "amenities": "WiFi, AC, Smart TV, Breakfast, City View, Mini Fridge, Work Desk",
    },
    {
        "room_type": "Family Room",
        "description": "Large room designed for families with comfortable sleeping space.",
        "capacity": 4,
        "total_rooms": 8,
        "amenities": "WiFi, AC, Smart TV, Breakfast, Extra Seating, Mini Fridge",
    },
    {
        "room_type": "Suite",
        "description": "Spacious suite with a separate living area for a premium stay.",
        "capacity": 4,
        "total_rooms": 4,
        "amenities": "WiFi, AC, Smart TV, Breakfast, Living Area, Mini Fridge, Sofa",
    },
]


ROOM_BASE_PRICES = {
    "Executive Room": Decimal("3200"),
    "Deluxe Premium Room": Decimal("3800"),
    "Family Room": Decimal("4600"),
    "Suite": Decimal("6500"),
}


MENU = [
    # Breakfast
    (
        "Poha",
        "Light flattened-rice breakfast with vegetables and peanuts.",
        "Breakfast",
        "120",
    ),
    (
        "Aloo Paratha",
        "Two stuffed potato parathas served with curd and pickle.",
        "Breakfast",
        "160",
    ),
    (
        "Paneer Paratha",
        "Two paneer-stuffed parathas served with curd and pickle.",
        "Breakfast",
        "190",
    ),
    (
        "Masala Dosa",
        "Crispy dosa served with sambar and coconut chutney.",
        "Breakfast",
        "180",
    ),
    (
        "Idli Sambar",
        "Steamed idlis served with sambar and chutney.",
        "Breakfast",
        "150",
    ),
    (
        "Veg Upma",
        "South Indian semolina breakfast with vegetables.",
        "Breakfast",
        "130",
    ),
    (
        "Bread Omelette",
        "Egg omelette with toasted bread.",
        "Breakfast",
        "170",
    ),
    (
        "Fruit & Yogurt Bowl",
        "Seasonal fruits with chilled yogurt and honey.",
        "Breakfast",
        "180",
    ),
    # Lunch
    (
        "Veg Thali",
        "Complete vegetarian meal with dal, vegetables, roti, rice and dessert.",
        "Lunch",
        "280",
    ),
    (
        "Dal Tadka Rice",
        "Yellow dal tempered with spices, served with steamed rice.",
        "Lunch",
        "240",
    ),
    (
        "Paneer Butter Masala",
        "Paneer cooked in a rich tomato and butter gravy.",
        "Lunch",
        "320",
    ),
    (
        "Kadhai Paneer",
        "Paneer and vegetables cooked in a spiced kadai gravy.",
        "Lunch",
        "320",
    ),
    (
        "Veg Biryani",
        "Aromatic basmati rice cooked with vegetables and whole spices.",
        "Lunch",
        "290",
    ),
    (
        "Jeera Rice",
        "Basmati rice tempered with cumin.",
        "Lunch",
        "170",
    ),
    (
        "Dal Makhani",
        "Slow-cooked black lentils in a creamy tomato gravy.",
        "Lunch",
        "260",
    ),
    (
        "Butter Naan",
        "Soft Indian flatbread finished with butter.",
        "Lunch",
        "70",
    ),
    # Tea & Coffee
    (
        "Masala Tea",
        "Indian tea brewed with milk and aromatic spices.",
        "Tea & Coffee",
        "60",
    ),
    (
        "Ginger Tea",
        "Fresh ginger tea with milk.",
        "Tea & Coffee",
        "65",
    ),
    (
        "Green Tea",
        "Light green tea served hot.",
        "Tea & Coffee",
        "70",
    ),
    (
        "Filter Coffee",
        "South Indian style filter coffee.",
        "Tea & Coffee",
        "90",
    ),
    (
        "Cappuccino",
        "Espresso with steamed milk and foam.",
        "Tea & Coffee",
        "140",
    ),
    # Evening Snacks
    (
        "Veg Sandwich",
        "Grilled sandwich with fresh vegetables and cheese.",
        "Evening Snacks",
        "160",
    ),
    (
        "Paneer Tikka",
        "Marinated paneer grilled with peppers and onions.",
        "Evening Snacks",
        "280",
    ),
    (
        "Veg Pakora",
        "Crispy assorted vegetable fritters.",
        "Evening Snacks",
        "180",
    ),
    (
        "Samosa",
        "Two crisp pastry samosas with chutney.",
        "Evening Snacks",
        "100",
    ),
    (
        "French Fries",
        "Crispy potato fries with seasoning.",
        "Evening Snacks",
        "160",
    ),
    (
        "Masala Maggi",
        "Noodles cooked with vegetables and Indian spices.",
        "Evening Snacks",
        "140",
    ),
    # Dinner
    (
        "Shahi Paneer",
        "Paneer in a mildly sweet and creamy gravy.",
        "Dinner",
        "330",
    ),
    (
        "Mix Veg Curry",
        "Seasonal vegetables cooked in a rich Indian gravy.",
        "Dinner",
        "280",
    ),
    (
        "Dal Tadka",
        "Yellow lentils tempered with garlic and spices.",
        "Dinner",
        "220",
    ),
    (
        "Veg Pulao",
        "Fragrant basmati rice with seasonal vegetables.",
        "Dinner",
        "240",
    ),
    (
        "Tandoori Roti",
        "Clay-oven baked whole-wheat Indian bread.",
        "Dinner",
        "50",
    ),
    (
        "Garlic Naan",
        "Soft naan topped with garlic and coriander.",
        "Dinner",
        "100",
    ),
    # Dessert
    (
        "Gulab Jamun",
        "Two warm gulab jamuns served in light sugar syrup.",
        "Dessert",
        "90",
    ),
    (
        "Gajar Halwa",
        "Traditional carrot dessert with milk and nuts.",
        "Dessert",
        "140",
    ),
    (
        "Ice Cream",
        "Two scoops of assorted ice cream.",
        "Dessert",
        "150",
    ),
    (
        "Fresh Fruit Platter",
        "Seasonal fresh fruit selection.",
        "Dessert",
        "180",
    ),
    # Beverages
    (
        "Fresh Lime Soda",
        "Refreshing lime soda served chilled.",
        "Beverages",
        "110",
    ),
    (
        "Mango Lassi",
        "Thick chilled yogurt drink blended with mango.",
        "Beverages",
        "140",
    ),
    (
        "Sweet Lassi",
        "Traditional chilled sweet yogurt drink.",
        "Beverages",
        "120",
    ),
    (
        "Mineral Water",
        "Packaged drinking water.",
        "Beverages",
        "40",
    ),
]


POLICIES = [
    (
        "check_in",
        "Check-in and Check-out",
        "Standard check-in is from 2:00 PM and check-out is by 11:00 AM.",
    ),
    (
        "identification",
        "Guest Identification",
        "Guests must present a valid government-issued photo ID at check-in.",
    ),
    (
        "cancellation",
        "Cancellation Policy",
        "Free cancellation is available up to 24 hours before check-in. "
        "Late cancellation or no-show may be charged according to booking terms.",
    ),
    (
        "children",
        "Children Policy",
        "Children are welcome. One child below 6 years can stay using "
        "existing bedding at no additional room charge.",
    ),
    (
        "extra_bed",
        "Extra Bed",
        "Extra beds are subject to room capacity and availability. Additional charges may apply.",
    ),
    (
        "early_check_in",
        "Early Check-in",
        "Early check-in is subject to room availability and may attract an additional charge.",
    ),
    (
        "late_check_out",
        "Late Check-out",
        "Late check-out is subject to availability and may attract an additional charge.",
    ),
    (
        "payment",
        "Payment",
        "Guests can pay using supported online payment methods or at the hotel desk.",
    ),
    (
        "smoking",
        "Smoking Policy",
        "Smoking is not permitted inside guest rooms. Designated smoking areas may be used.",
    ),
]


FAQS = [
    (
        "What time is check-in?",
        "Check-in starts at 2:00 PM.",
        "Check-in",
    ),
    (
        "What time is check-out?",
        "Check-out is by 11:00 AM.",
        "Check-out",
    ),
    (
        "Is breakfast included?",
        "Breakfast is included with selected room rates. The applicable "
        "rate should be checked for the booking dates.",
        "Food",
    ),
    (
        "Do you provide Wi-Fi?",
        "Yes. Wi-Fi is available for hotel guests.",
        "Facilities",
    ),
    (
        "Is parking available?",
        "Yes. Complimentary on-site parking is available subject to space.",
        "Facilities",
    ),
    (
        "Do you provide airport transfers?",
        "Yes. Airport transfer can be requested as a paid hotel service.",
        "Transport",
    ),
    (
        "Can I request an extra bed?",
        "Yes, subject to room capacity and availability. Additional charges may apply.",
        "Rooms",
    ),
    (
        "Do you have vegetarian food?",
        "Yes. The hotel restaurant offers vegetarian breakfast, lunch, snacks and dinner options.",
        "Food",
    ),
    (
        "Can I order food to my room?",
        "Yes. Room-service ordering is available during restaurant service hours.",
        "Food",
    ),
    (
        "Is the hotel suitable for families?",
        "Yes. Family rooms and family-friendly facilities are available.",
        "Rooms",
    ),
]


SERVICES = [
    (
        "Airport Transfer",
        "Pre-arranged pickup or drop-off between the hotel and Jaipur airport.",
        "Transport",
        "900",
    ),
    (
        "Laundry Service",
        "Laundry and basic garment care service for hotel guests.",
        "Housekeeping",
        "250",
    ),
    (
        "Room Service",
        "Food and beverage delivery to guest rooms during service hours.",
        "Food",
        "0",
    ),
    (
        "Housekeeping Request",
        "On-request additional housekeeping and room refresh.",
        "Housekeeping",
        "0",
    ),
    (
        "Extra Bed",
        "Additional bed subject to room capacity and availability.",
        "Room",
        "800",
    ),
    (
        "Travel Desk",
        "Assistance with local sightseeing, cabs and travel arrangements.",
        "Travel",
        "0",
    ),
    (
        "Early Check-in",
        "Early room access subject to availability.",
        "Room",
        "500",
    ),
    (
        "Late Check-out",
        "Extended check-out subject to availability.",
        "Room",
        "500",
    ),
]


OFFERS = [
    (
        "Weekend Stay Offer",
        "Get 10% off eligible room bookings for weekend stays.",
        "PERCENTAGE",
        "10",
        date(2026, 9, 21),
        date(2026, 12, 31),
    ),
    (
        "Early Booking Offer",
        "Get 12% off when an eligible stay is booked at least 7 days in advance.",
        "PERCENTAGE",
        "12",
        date(2026, 9, 21),
        date(2026, 12, 31),
    ),
    (
        "Long Stay Offer",
        "Get 15% off eligible stays of 5 nights or more.",
        "PERCENTAGE",
        "15",
        date(2026, 9, 21),
        date(2026, 12, 31),
    ),
    (
        "Festive Season Offer",
        "Flat ₹500 discount on selected room bookings during the festive season.",
        "FIXED",
        "500",
        date(2026, 10, 1),
        date(2026, 11, 15),
    ),
]


def get_or_create(session, model, filters, values):
    instance = session.scalar(select(model).filter_by(**filters))

    if instance is None:
        instance = model(**filters, **values)
        session.add(instance)
    else:
        for key, value in values.items():
            setattr(instance, key, value)

    return instance


def seed_hotel(session):
    hotel = session.get(Hotel, HOTEL_ID)

    if hotel is None:
        hotel = Hotel(
            id=HOTEL_ID,
            name="StayFlow Grand Hotel",
            description=(
                "A modern city hotel in Jaipur with comfortable rooms, "
                "dining, guest services and AI-assisted hospitality support."
            ),
            city="Jaipur",
            address="Jaipur, Rajasthan, India",
            phone="+91 98765 43210",
            email="stayflowgrand@example.com",
            timezone="Asia/Kolkata",
            currency="INR",
            is_active=True,
        )
        session.add(hotel)
    else:
        hotel.name = "StayFlow Grand Hotel"
        hotel.description = (
            "A modern city hotel in Jaipur with comfortable rooms, "
            "dining, guest services and AI-assisted hospitality support."
        )
        hotel.city = "Jaipur"
        hotel.address = "Jaipur, Rajasthan, India"
        hotel.phone = "+91 98765 43210"
        hotel.email = "stayflowgrand@example.com"
        hotel.timezone = "Asia/Kolkata"
        hotel.currency = "INR"
        hotel.is_active = True

    session.flush()


def seed_rooms(session):
    rooms = {}

    for data in ROOMS:
        room_type = data["room_type"]

        room = get_or_create(
            session,
            Room,
            {
                "hotel_id": HOTEL_ID,
                "room_type": room_type,
            },
            {
                "description": data["description"],
                "capacity": data["capacity"],
                "total_rooms": data["total_rooms"],
                "amenities": data["amenities"],
                "is_active": True,
            },
        )

        session.flush()
        rooms[room_type] = room

    return rooms


def seed_rates_and_availability(session, rooms):
    current = START_DATE

    while current <= END_DATE:
        weekend_surcharge = Decimal("400") if current.weekday() >= 5 else Decimal("0")

        for room_type, room in rooms.items():
            base_price = ROOM_BASE_PRICES[room_type]

            seasonal_surcharge = Decimal("700") if current.day in {24, 25, 26} else Decimal("0")

            price = base_price + weekend_surcharge + seasonal_surcharge

            available_rooms = room.total_rooms

            # Keep some realistic low-availability dates for testing.
            if room_type == "Deluxe Premium Room" and current in {
                date(2026, 9, 22),
                date(2026, 9, 23),
            }:
                available_rooms = 1

            elif room_type == "Suite" and current in {
                date(2026, 9, 27),
                date(2026, 9, 28),
            }:
                available_rooms = 0

            get_or_create(
                session,
                Rate,
                {
                    "room_id": room.id,
                    "date": current,
                },
                {
                    "price": price,
                    "currency": "INR",
                    "is_active": True,
                },
            )

            get_or_create(
                session,
                Availability,
                {
                    "room_id": room.id,
                    "date": current,
                },
                {
                    "available_rooms": available_rooms,
                    "is_active": True,
                },
            )

        current += timedelta(days=1)


def seed_policies(session):
    for policy_type, title, description in POLICIES:
        get_or_create(
            session,
            Policy,
            {
                "hotel_id": HOTEL_ID,
                "policy_type": policy_type,
            },
            {
                "title": title,
                "description": description,
                "is_active": True,
            },
        )


def seed_faqs(session):
    for question, answer, category in FAQS:
        get_or_create(
            session,
            FAQ,
            {
                "hotel_id": HOTEL_ID,
                "question": question,
            },
            {
                "answer": answer,
                "category": category,
                "is_active": True,
            },
        )


def seed_services(session):
    for name, description, category, price in SERVICES:
        get_or_create(
            session,
            Service,
            {
                "hotel_id": HOTEL_ID,
                "name": name,
            },
            {
                "description": description,
                "category": category,
                "price": Decimal(price),
                "is_active": True,
            },
        )


def seed_offers(session):
    for (
        name,
        description,
        discount_type,
        discount_value,
        valid_from,
        valid_until,
    ) in OFFERS:
        get_or_create(
            session,
            Offer,
            {
                "hotel_id": HOTEL_ID,
                "name": name,
            },
            {
                "description": description,
                "discount_type": discount_type,
                "discount_value": Decimal(discount_value),
                "valid_from": valid_from,
                "valid_until": valid_until,
                "is_active": True,
            },
        )


def seed_menu(session):
    for name, description, category, price in MENU:
        get_or_create(
            session,
            MenuItem,
            {
                "hotel_id": HOTEL_ID,
                "name": name,
            },
            {
                "description": description,
                "category": category,
                "price": Decimal(price),
                "is_available": True,
                "is_active": True,
            },
        )


def main():
    with SessionLocal() as session:
        seed_hotel(session)

        rooms = seed_rooms(session)

        seed_rates_and_availability(
            session,
            rooms,
        )

        seed_policies(session)
        seed_faqs(session)
        seed_services(session)
        seed_offers(session)
        seed_menu(session)

        session.commit()

    print("StayFlow Grand Hotel demo data seeded successfully.")


if __name__ == "__main__":
    main()
