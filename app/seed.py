"""Optional demo fixtures (accounts, restaurant catalogue, sample orders).

The catalogue is Karachi-based: real city areas (Saddar, Bahadurabad,
Clifton, Gulshan-e-Iqbal, PECHS, Burns Road), Karachi coordinates and
Pakistani-Rupee menu prices. This is *not* the ML dataset - it only gives
the web application something to show on a fresh installation. Real data
ingestion / model training is handled by the scripts/ + ml/ module.
"""
from __future__ import annotations

from datetime import timedelta

from .extensions import db
from .models import (
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_DELIVERY,
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    CustomerProfile,
    DeliveryPartnerProfile,
    Feedback,
    MenuItem,
    Order,
    OrderItem,
    Restaurant,
    User,
)
from .services.settings import ensure_defaults, get_float
from .utils import as_decimal, format_money, generate_order_number, haversine_km, utcnow

DEMO_PASSWORD = "Password@123"

CITY = "Karachi"
PROVINCE = "Sindh"

RESTAURANTS = [
    {
        "name": "Karachi Grill House",
        "cuisine": "Pakistani BBQ",
        "description": "Charcoal-grilled kababs, simmering karahis and hot tandoori naan straight from Saddar.",
        "address": "Shop 5, Elphinstone Street, Saddar",
        "city": CITY,
        "phone": "+92 333 121 1001",
        "email": "grill@moonlight.pk",
        "latitude": 24.8592,
        "longitude": 67.0330,
        "opening_time": "12:00",
        "closing_time": "23:30",
        "items": [
            ("Chicken Karahi (Half)", "Pakistani", 1650, False, 30),
            ("Seekh Kabab (6 pcs)", "BBQ", 680, False, 18),
            ("Malai Boti", "BBQ", 720, False, 20),
            ("Roghni Naan", "Breads", 60, True, 6),
            ("Fresh Salad & Raita", "Sides", 130, True, 5),
            ("Gulab Jamun (4 pcs)", "Desserts", 250, True, 5),
        ],
    },
    {
        "name": "Bahadurabad Biryani House",
        "cuisine": "Biryani & Rice",
        "description": "Sindhi-style dum biryani, shola and jhol - the Bahadurabad biryani legend since 1981.",
        "address": "Ground floor, Bahadurabad Chowrangi",
        "city": CITY,
        "phone": "+92 333 121 1002",
        "email": "biryani@moonlight.pk",
        "latitude": 24.8795,
        "longitude": 67.0595,
        "opening_time": "11:00",
        "closing_time": "01:00",
        "items": [
            ("Sindhi Chicken Biryani", "Biryani", 380, False, 25),
            ("Beef Biryani", "Biryani", 420, False, 28),
            ("Chicken Tikka Biryani", "Biryani", 450, False, 28),
            ("Aloo Zafrani Biryani (Veg)", "Biryani", 320, True, 24),
            ("Chicken Jhol with Naan", "Pakistani", 350, False, 15),
            ("Sewaiyan Kheer", "Desserts", 220, True, 6),
        ],
    },
    {
        "name": "Clifton Seafood Co.",
        "cuisine": "Seafood",
        "description": "Day-boat karachi catch: grilled pomfret, prawn masala and coastal fish tikka near Seawiew.",
        "address": "Khayaban-e-Saadi, Clifton Block 2",
        "city": CITY,
        "phone": "+92 333 121 1003",
        "email": "seafood@moonlight.pk",
        "latitude": 24.8140,
        "longitude": 67.0300,
        "opening_time": "12:30",
        "closing_time": "23:00",
        "items": [
            ("Grilled Whole Pomfret", "Seafood", 1850, False, 32),
            ("Fish Tikka Masala", "Seafood", 950, False, 22),
            ("Prawn Handi Masala", "Seafood", 1650, False, 26),
            ("Batata Fish Pakora", "Starters", 750, False, 14),
            ("Lemon Mint Soda", "Beverages", 180, True, 4),
        ],
    },
    {
        "name": "Gulshan Green Bowl",
        "cuisine": "Healthy Cafe",
        "description": "Protein bowls, salads and smoothies for Gulshan joggers and gym-goers.",
        "address": "Block 10, Rashid Minhas Road, Gulshan-e-Iqbal",
        "city": CITY,
        "phone": "+92 333 121 1004",
        "email": "greenbowl@moonlight.pk",
        "latitude": 24.9185,
        "longitude": 67.0925,
        "opening_time": "08:00",
        "closing_time": "22:00",
        "items": [
            ("Chicken Caesar Salad", "Salads", 640, False, 14),
            ("Grilled Chicken & Quinoa Bowl", "Bowls", 780, False, 18),
            ("Berry Protein Smoothie", "Beverages", 480, True, 7),
            ("Avocado Sourdough Toast", "Breakfast", 560, True, 10),
            ("Hummus & Pita Plate", "Starters", 520, True, 10),
        ],
    },
    {
        "name": "PECHS Wood Fire Pizza",
        "cuisine": "Italian Pizza",
        "description": "Wood-fired neapolitan pizzas, creamy pastas and Karachi's favourite lava cake.",
        "address": "Block 6 caf strip, PECHS",
        "city": CITY,
        "phone": "+92 333 121 1005",
        "email": "pizza@moonlight.pk",
        "latitude": 24.8612,
        "longitude": 67.0512,
        "opening_time": "11:00",
        "closing_time": "23:45",
        "items": [
            ("Classic Margherita 12in", "Pizza", 950, True, 18),
            ("Chicken Tikka Pizza", "Pizza", 1350, False, 20),
            ("Creamy Chicken Fajita Pizza", "Pizza", 1450, False, 21),
            ("Cheesy Garlic Bread", "Sides", 450, True, 10),
            ("Choco Lava Cake", "Desserts", 420, True, 8),
            ("Iced Cappuccino", "Beverages", 350, True, 6),
        ],
    },
    {
        "name": "Burns Road Chaat & Haleem",
        "cuisine": "Desi Street Food",
        "description": "Legendary Burns Road haleem, chaat, dahi bhalla and falooda straight from the food street.",
        "address": "Burns Road, Old City Area",
        "city": CITY,
        "phone": "+92 333 121 1006",
        "email": "burnsroad@moonlight.pk",
        "latitude": 24.8505,
        "longitude": 67.0365,
        "opening_time": "16:00",
        "closing_time": "01:30",
        "items": [
            ("Beef Haleem (Single)", "Desi", 480, False, 20),
            ("Chaat Platter", "Chaat", 380, True, 8),
            ("Dahi Bhalla", "Chaat", 300, True, 6),
            ("Royal Falooda", "Desserts", 350, True, 7),
            ("Chicken Bihari Roll", "Rolls", 320, False, 12),
        ],
    },
]


def _ensure_user(name, username, email, role, phone="", address="", city=CITY) -> User:
    user = User.query.filter(
        db.or_(User.username == username, User.email == email)
    ).first()
    if user is not None:
        return user
    user = User(name=name, username=username, email=email, phone=phone, role=role, is_active=True)
    user.set_password(DEMO_PASSWORD)
    if role == ROLE_CUSTOMER:
        user.customer_profile = CustomerProfile(
            address=address,
            city=city,
            state=PROVINCE,
            pincode="75400",
            latitude=24.8606,
            longitude=67.0503,
            food_preferences="Biryani, BBQ, Karahi",
        )
    elif role == ROLE_DELIVERY:
        user.partner_profile = DeliveryPartnerProfile(
            vehicle_type="Bike",
            vehicle_number=f"KHI-{username[-1:].zfill(4)}",
            is_available=True,
        )
    db.session.add(user)
    return user


def _ensure_restaurant(data: dict) -> Restaurant:
    restaurant = Restaurant.query.filter_by(name=data["name"]).first()
    if restaurant is None:
        from datetime import datetime as _dt

        restaurant = Restaurant(
            name=data["name"],
            cuisine=data["cuisine"],
            description=data["description"],
            address=data["address"],
            city=data["city"],
            phone=data["phone"],
            email=data["email"],
            latitude=data["latitude"],
            longitude=data["longitude"],
            opening_time=_dt.strptime(data["opening_time"], "%H:%M").time(),
            closing_time=_dt.strptime(data["closing_time"], "%H:%M").time(),
            is_active=True,
        )
        db.session.add(restaurant)
        db.session.flush()
    for name, category, price, is_veg, prep in data["items"]:
        if not MenuItem.query.filter_by(restaurant_id=restaurant.id, name=name).first():
            db.session.add(
                MenuItem(
                    restaurant_id=restaurant.id,
                    name=name,
                    category=category,
                    price=as_decimal(price),
                    is_veg=is_veg,
                    prep_time_min=prep,
                    description=f"Freshly prepared {name.lower()}.",
                    is_available=True,
                )
            )
    return restaurant


def _seed_orders(customers: list[User], partners: list[User], restaurants: list[Restaurant]) -> int:
    if Order.query.count() > 0:
        return 0
    created = 0
    now = utcnow()
    for index in range(30):
        restaurant = restaurants[index % len(restaurants)]
        customer = customers[index % len(customers)]
        menu_items = restaurant.menu_items.all()
        if not menu_items:
            continue
        item = menu_items[index % len(menu_items)]
        quantity = 1 + (index % 3)
        subtotal = as_decimal(item.price) * quantity
        distance = round(2.0 + (index % 9) * 1.2, 2)
        fee = as_decimal(get_float("base_delivery_fee", 60)) + as_decimal(
            get_float("per_km_fee", 25)
        ) * as_decimal(distance)
        placed = now - timedelta(days=max(0, index - 6) % 14, hours=1 + (index % 9), minutes=index * 5)
        cancelled = index in {7, 13, 23}
        delivered = not cancelled
        # keep the newest six orders in an active lifecycle state so the
        # assignment / route-optimizer demo has work to do immediately
        active_status = None if index >= 6 else ("placed", "confirmed", "prepared", "dispatched")[index % 4]
        if active_status:
            delivered = False
            status = active_status
            partner = partners[index % len(partners)] if active_status in ("prepared", "dispatched") else None
        else:
            partner = partners[index % len(partners)] if delivered else None
            status = STATUS_DELIVERED if delivered else STATUS_CANCELLED
        # Karachi cluster around the customer profile coordinates
        delivery_lat = 24.8606 + (index % 5) * 0.004
        delivery_lng = 67.0503 + (index % 4) * 0.004
        order = Order(
            order_number=generate_order_number() + str(index),
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            delivery_partner_id=partner.id if partner else None,
            status=status,
            payment_method=("COD", "Easypaisa", "Card")[index % 3],
            payment_status="Collected" if delivered and index % 3 == 0 else ("Paid" if delivered else ("Pending" if status in ("placed", "confirmed") else "Refunded")),
            subtotal=subtotal,
            delivery_fee=fee,
            total=subtotal + fee,
            delivery_address=customer.customer_profile.full_address,
            delivery_lat=delivery_lat,
            delivery_lng=delivery_lng,
            distance_km=distance,
            estimated_delivery_min=35 + (index % 12),
            placed_at=placed,
            confirmed_at=placed + timedelta(minutes=2) if status != STATUS_CANCELLED else None,
            prepared_at=placed + timedelta(minutes=16) if status in ("prepared", "dispatched", STATUS_DELIVERED) else None,
            dispatched_at=placed + timedelta(minutes=21) if status in ("dispatched", STATUS_DELIVERED) else None,
            delivered_at=placed + timedelta(minutes=39) if delivered else None,
            cancelled_at=placed + timedelta(minutes=8) if cancelled else None,
            cancellation_reason="Customer changed their mind" if cancelled else None,
        )
        order.items.append(
            OrderItem(
                menu_item=item,
                item_name=item.name,
                category=item.category,
                unit_price=item.price,
                quantity=quantity,
                line_total=subtotal,
            )
        )
        db.session.add(order)
        if delivered and partner and partner.partner_profile:
            partner.partner_profile.total_deliveries += 1
            if index % 3 != 0:
                rating = 4 if index % 4 else 5
                order.feedback = Feedback(
                    customer_id=customer.id,
                    restaurant_id=restaurant.id,
                    partner_id=partner.id,
                    restaurant_rating=rating,
                    partner_rating=rating,
                    comment="Great food and quick delivery." if rating == 5 else "Good food, partner was on time.",
                    created_at=placed + timedelta(minutes=42),
                )
        created += 1
    db.session.flush()
    # Recompute rating aggregates from the seeded feedback.
    for restaurant in restaurants:
        ratings = [f.restaurant_rating for f in Feedback.query.filter_by(restaurant_id=restaurant.id).all()]
        restaurant.rating_count = len(ratings)
        restaurant.rating_avg = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    for partner in partners:
        ratings = [f.partner_rating for f in Feedback.query.filter_by(partner_id=partner.id).all() if f.partner_rating]
        if partner.partner_profile:
            partner.partner_profile.rating_count = len(ratings)
            partner.partner_profile.rating_avg = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    return created


def seed_demo(with_orders: bool = False) -> str:
    db.create_all()
    ensure_defaults()

    admin = _ensure_user("Operations Director", "admin", "admin@moonlight.pk", ROLE_ADMIN, "+92 300 000 0001")
    customer = _ensure_user(
        "Hamza Iqbal", "hamza", "hamza@moonlight.pk", ROLE_CUSTOMER,
        "+92 301 234 5678", "Flat 4-B, Zarina Street, PECHS Block 6",
    )
    customer2 = _ensure_user(
        "Ayesha Siddiqui", "ayesha", "ayesha@moonlight.pk", ROLE_CUSTOMER,
        "+92 302 345 6789", "Villa 21, Khayaban-e-Bukhari, DHA Phase 6",
    )
    customer3 = _ensure_user(
        "Bilal Ahmed", "bilal", "bilal@moonlight.pk", ROLE_CUSTOMER,
        "+92 303 456 7890", "House 44, Block 13-D, Gulshan-e-Iqbal",
    )
    partners = [
        _ensure_user("Daniyal Raza", "partner1", "partner1@moonlight.pk", ROLE_DELIVERY, "+92 311 900 0011"),
        _ensure_user("Sana Khan", "partner2", "partner2@moonlight.pk", ROLE_DELIVERY, "+92 312 900 0012"),
        _ensure_user("Faizan Malik", "partner3", "partner3@moonlight.pk", ROLE_DELIVERY, "+92 313 900 0013"),
    ]
    db.session.flush()

    # individualised saved addresses
    customer2.customer_profile.latitude = 24.8247
    customer2.customer_profile.longitude = 67.0652
    customer2.customer_profile.pincode = "75500"
    customer2.customer_profile.updated_at = utcnow()
    customer3.customer_profile.latitude = 24.9180
    customer3.customer_profile.longitude = 67.0924
    customer3.customer_profile.pincode = "75300"
    customer3.customer_profile.updated_at = utcnow()

    for partner, (lat, lng) in zip(
        partners, [
            (24.8700, 67.0600),   # partner1 - Tariq Road
            (24.8140, 67.0300),   # partner2 - Clifton
            (24.9180, 67.0924),   # partner3 - Gulshan-e-Iqbal
        ]
    ):
        if partner.partner_profile and partner.partner_profile.current_lat is None:
            partner.partner_profile.current_lat = lat
            partner.partner_profile.current_lng = lng
            partner.partner_profile.last_location_at = utcnow()

    restaurants = [_ensure_restaurant(data) for data in RESTAURANTS]
    db.session.commit()

    orders_created = 0
    if with_orders:
        orders_created = _seed_orders([customer, customer2, customer3], partners, restaurants)
        db.session.commit()

    lines = [
        "Karachi demo data ready.",
        f"  Admin     : admin / {DEMO_PASSWORD}",
        f"  Customers : hamza, ayesha, bilal / {DEMO_PASSWORD}",
        f"  Partners  : partner1, partner2, partner3 / {DEMO_PASSWORD}",
        f"  Restaurants: {len(restaurants)} Karachi kitchens with menu items",
    ]
    if with_orders:
        lines.append(f"  Sample orders: {orders_created}")
    lines.append(f"  Demo order value example: {format_money(380)}")
    return "\n".join(lines)
