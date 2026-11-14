"""Live demo order simulator.

Har minute 2 naye orders spawn karta hai (random customer + restaurant) aur
unke lifecycle ko dheeray dheeray advance karta hai (confirmed -> prepared ->
dispatched -> delivered) taake partner dashboards pe live income aur new
requests ka feel aaye. Admin > Settings se on/off + rate control hota hai.

Notes field "SIM: ..." se sim orders identify hote hain - real orders is se
kabhi touch nahi hote. (SQL Server LIKE mein '[' wildcard hai, is liye
plain prefix rakha hai.)
"""
from __future__ import annotations

import logging
import os
import random
import threading
from datetime import timedelta
from decimal import Decimal

from ..extensions import db
from ..models import (
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_DELIVERY,
    STATUS_CONFIRMED,
    STATUS_DELIVERED,
    STATUS_DISPATCHED,
    STATUS_PREPARED,
    CustomerProfile,
    DeliveryPartnerProfile,
    Order,
    OrderItem,
    Restaurant,
    User,
)
from ..utils import as_decimal, format_money, generate_order_number, haversine_km, utcnow
from .assignment import assign_order, auto_assign_order
from .routing import estimate_eta
from .notifications import notify, notify_admins
from .settings import get_bool, get_float, get_int

SIM_NOTE = "SIM: Live demo order"

# simulator ke fauran recognise karne ke liye notes ka pehla token
SIM_MARK = "SIM:"

MAX_PARTNERS = 14  # fleet cap taake demo unlimited riders na hire kare

RIDER_NAMES = ["Adeel", "Imran", "Sajid", "Kashif", "Naveed", "Zubair", "Faisal",
               "Shoaib", "Tanveer", "Rashid", "Junaid", "Aamir", "Sohail", "Waqar"]

logger = logging.getLogger("simulator")

DROP_POINTS = [
    (24.8230, 67.0700, "House 22, Khayaban-e-Bukhari, DHA Phase 6"),
    (24.8140, 67.0340, "Flat 5B, Khayaban-e-Saadi, Clifton Block 2"),
    (24.9185, 67.0960, "Flat 8A, Block 10-A, Gulshan-e-Iqbal"),
    (24.9420, 67.0440, "House R-45, Block M, North Nazimabad"),
    (24.8680, 67.0640, "Apartment 12, Tariq Road, PECHS Block 2"),
    (24.8930, 67.2100, "House 9, Malir 15, Malir"),
    (24.8660, 66.9880, "Flat 3, Agha Khan Road, Lyari Town"),
    (24.8870, 67.1500, "House 71, Block 5, Federal B Area"),
    (24.8560, 67.1100, "Flat 2C, Bahadur Yar Jung Road, Jamshed Town"),
    (24.8990, 67.0260, "House B-14,Nazimabad Golimar Chowk"),
]

PAYMENTS = ("COD", "COD", "Easypaisa", "Card")


def _sim_orders_active():
    return Order.query.filter(
        Order.notes.like(SIM_MARK + "%"),
        Order.status.in_(("confirmed", "prepared", "dispatched", "placed")),
    ).count()


def spawn_orders(count: int = 2) -> list[Order]:
    """Naye simulated orders banao (checkout jaisa flow, confirmed status)."""
    customers = (
        User.query.join(CustomerProfile)
        .filter(User.role == ROLE_CUSTOMER, User.is_active.is_(True))
        .all()
    )
    restaurants = [r for r in Restaurant.query.filter_by(is_active=True).all() if r.menu_items.count()]
    if not customers or not restaurants:
        return []

    created: list[Order] = []
    for _ in range(count):
        customer = random.choice(customers)
        restaurant = random.choice(restaurants)
        items = random.sample(list(restaurant.menu_items.filter_by(is_available=True)), k=random.randint(1, 3))

        lat, lng, address = random.choice(DROP_POINTS)
        distance = (
            haversine_km(restaurant.latitude, restaurant.longitude, lat, lng)
            if restaurant.has_location else 0.0
        )
        fee = as_decimal(get_float("base_delivery_fee", 60)) + as_decimal(get_float("per_km_fee", 25)) * as_decimal(distance)

        subtotal = Decimal("0")
        picked = [(item, random.randint(1, 2)) for item in items]
        order = Order(
            order_number=generate_order_number(),
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            status=STATUS_CONFIRMED,
            confirmed_at=utcnow(),
            placed_at=utcnow(),
            payment_method=random.choice(PAYMENTS),
            payment_status="Paid" if random.random() < 0.4 else "Pending",
            delivery_fee=fee,
            delivery_address=address,
            delivery_lat=lat,
            delivery_lng=lng,
            distance_km=round(distance, 2),
            notes=SIM_NOTE,
        )
        for item, qty in picked:
            subtotal += as_decimal(item.price) * qty
            order.items.append(
                OrderItem(
                    menu_item=item,
                    item_name=item.name,
                    category=item.category,
                    unit_price=item.price,
                    quantity=qty,
                    line_total=as_decimal(item.price) * qty,
                )
            )
        order.subtotal = subtotal
        order.total = subtotal + fee

        db.session.add(order)
        db.session.flush()
        # rider pehle assign -> ETA real rider features ke sath (full-accuracy path)
        auto_assign_order(order)  # sab partners busy hon to open job ban jata hai
        if not order.estimated_delivery_min:
            order.estimated_delivery_min = estimate_eta(order)
        notify_admins(
            "New order received",
            f"{order.order_number} - {restaurant.name} ({format_money(order.total)}).",
            "order",
        )
        notify(
            customer.id,
            "Order confirmed",
            f"{order.order_number} from {restaurant.name} is confirmed.",
            "order",
        )
        created.append(order)
    return created


def advance_lifecycle() -> int:
    """Sim orders ko ek step aage barhao (jahan time aa chuka ho). Returns advanced count."""
    now = utcnow()
    advanced = 0
    open_orders = (
        Order.query.filter(
            Order.notes.like(SIM_MARK + "%"),
            Order.status.in_(("confirmed", "prepared", "dispatched", "placed")),
        )
        .order_by(Order.placed_at.asc())
        .all()
    )
    for order in open_orders:
        age_min = (now - (order.placed_at or now)).total_seconds() / 60.0

        if order.status in ("placed", "confirmed"):
            # prepared hona chahiye; purana stuck order pehle partner dhoondo
            if order.delivery_partner_id is None and age_min > 4:
                _force_assign_random(order)
            if age_min > 3 and order.status != "placed":
                order.set_status(STATUS_PREPARED)
                advanced += 1

        elif order.status == STATUS_PREPARED:
            if order.delivery_partner_id is None:
                if age_min > 5:
                    _force_assign_random(order)
                else:
                    continue
            if age_min > 5:
                order.set_status(STATUS_DISPATCHED)
                advanced += 1

        elif order.status == STATUS_DISPATCHED:
            if age_min > 10:
                order.set_status(STATUS_DELIVERED)
                advanced += 1
                notify(
                    order.customer_id,
                    "Delivered",
                    f"{order.order_number} was delivered. Enjoy your meal!",
                    "order",
                )
    return advanced


def _force_assign_random(order: Order) -> None:
    # jis partner ke paas kam se kam active orders hain usay do
    chosen = least_workload_partner()
    if chosen:
        assign_order(order, chosen, actor="live-simulator", force=True)


def least_workload_partner():
    from ..models import ROLE_DELIVERY

    partners = User.query.filter_by(role=ROLE_DELIVERY, is_active=True).all()
    if not partners:
        return None
    return min(
        partners,
        key=lambda p: (p.partner_profile.active_order_count if p.partner_profile else 0, random.random()),
    )


def partner_fleet_stats() -> dict:
    """Partners ki capacity vs unassigned orders - hire ki zaroorat check karne ke liye."""
    from ..models import ACTIVE_STATUSES

    max_orders = get_int("max_orders_per_partner", 3)
    partners = [u for u in User.query.filter_by(role=ROLE_DELIVERY, is_active=True).all() if u.partner_profile]
    capacity = sum(max(0, max_orders - u.partner_profile.active_order_count) for u in partners)
    unassigned = Order.query.filter(
        Order.delivery_partner_id.is_(None),
        Order.status.in_(("confirmed", "prepared")),
    ).count()
    return {"partners": len(partners), "capacity": capacity, "unassigned": unassigned}


def hire_partner() -> User | None:
    """Orders ke hisab se naya rider fleet mein add karo (auto-hire)."""
    if User.query.filter_by(role=ROLE_DELIVERY).count() >= MAX_PARTNERS:
        return None
    idx = User.query.filter_by(role=ROLE_DELIVERY).count() + 1
    base_name = RIDER_NAMES[(idx - 1) % len(RIDER_NAMES)]
    username = f"rider{idx:02d}"
    if User.query.filter_by(username=username).first():
        return None
    lat, lng, _address = random.choice(DROP_POINTS)
    user = User(
        name=f"{base_name} (Rider {idx:02d})",
        username=username,
        email=f"rider{idx:02d}@moonlight.pk",
        phone=f"+92 30{random.randint(10, 99)} {random.randint(1000000, 9999999)}",
        role=ROLE_DELIVERY,
        is_active=True,
    )
    user.set_password("Password@123")
    user.partner_profile = DeliveryPartnerProfile(
        vehicle_type=random.choice(["Bike", "Bike", "Car"]),
        vehicle_number=f"KHI-{idx:04d}",
        is_available=True,
        current_lat=lat,
        current_lng=lng,
        last_location_at=utcnow(),
    )
    db.session.add(user)
    db.session.flush()
    notify_admins(
        "New partner hired",
        f"{user.name} joined the fleet to cover incoming order volume.",
        "system",
    )
    return user


def hire_if_needed(min_deficit: int = 2) -> int:
    """Jab unassigned orders capacity se zyada hon to riders hire karo. Returns hired count."""
    if not get_bool("auto_hire_partners", True):
        return 0
    hired = 0
    for _ in range(3):  # ek tick mein max 3 riders
        stats = partner_fleet_stats()
        if stats["unassigned"] - stats["capacity"] < min_deficit:
            break
        if hire_partner() is None:
            break
        hired += 1
    return hired


def cleanup_old_sim_orders(days: int = 3) -> int:
    """Purane delivered sim orders hatao taake demo DB phool na jaye."""
    cutoff = utcnow() - timedelta(days=days)
    old = (
        Order.query.filter(
            Order.notes.like(SIM_MARK + "%"),
            Order.status == STATUS_DELIVERED,
            Order.placed_at < cutoff,
        )
        .limit(200)
        .all()
    )
    for order in old:
        db.session.delete(order)
    return len(old)


def run_tick(app) -> None:
    """Ek simulator cycle: spawn + lifecycle + cleanup (apna app context).

    test_request_context is liye ke assignment/notifications ke andar
    url_for() use hota hai jo request context maangta hai.
    """
    try:
        with app.test_request_context("/"):
            # fleet order volume cover kare (simulation off ho tab bhi)
            hire_if_needed()
            if get_bool("live_order_simulation", True):
                per_minute = get_int("sim_orders_per_minute", 2)
                if per_minute > 0 and _sim_orders_active() < 40:
                    spawn_orders(per_minute)
                advance_lifecycle()
            cleanup_old_sim_orders()
            db.session.commit()
    except Exception:
        with app.app_context():
            db.session.rollback()
        logger.exception("simulator tick failed")


def _loop(app) -> None:
    import time

    # server startup ke foran baad pehla tick, phir har minute
    time.sleep(20)
    while True:
        run_tick(app)
        time.sleep(60)


def start(app) -> None:
    """App factory ke end mein call karo. Debug reloader parent mein skip."""
    if app.config.get("TESTING") or os.getenv("SIMULATE_ORDERS", "1").strip().lower() in {"0", "false", "off"}:
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if app.extensions.get("simulator_started"):
        return
    app.extensions["simulator_started"] = True
    thread = threading.Thread(target=_loop, args=(app,), name="live-order-simulator", daemon=True)
    thread.start()
    app.logger.info("Live order simulator started (2 orders/min, settings toggle: live_order_simulation)")
