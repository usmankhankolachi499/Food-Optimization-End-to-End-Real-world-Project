"""Database models for the Food Delivery Optimization System.

Structured data (users, restaurants, orders, partners, feedback, settings)
lives in the relational database. High-volume location logs can additionally
be mirrored to MongoDB through :mod:`app.services.tracking`.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .utils import format_money, generate_order_number


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
ROLE_CUSTOMER = "customer"
ROLE_DELIVERY = "delivery"
ROLE_ADMIN = "admin"
ROLES = (ROLE_CUSTOMER, ROLE_DELIVERY, ROLE_ADMIN)
ROLE_LABELS = {
    ROLE_CUSTOMER: "Customer",
    ROLE_DELIVERY: "Delivery Partner",
    ROLE_ADMIN: "Administrator",
}

STATUS_PLACED = "placed"
STATUS_CONFIRMED = "confirmed"
STATUS_PREPARED = "prepared"
STATUS_DISPATCHED = "dispatched"
STATUS_DELIVERED = "delivered"
STATUS_CANCELLED = "cancelled"

ORDER_STATUSES = (
    STATUS_PLACED,
    STATUS_CONFIRMED,
    STATUS_PREPARED,
    STATUS_DISPATCHED,
    STATUS_DELIVERED,
    STATUS_CANCELLED,
)
ACTIVE_STATUSES = (STATUS_PLACED, STATUS_CONFIRMED, STATUS_PREPARED, STATUS_DISPATCHED)
STATUS_FLOW = {
    STATUS_PLACED: [STATUS_CONFIRMED, STATUS_CANCELLED],
    STATUS_CONFIRMED: [STATUS_PREPARED, STATUS_CANCELLED],
    STATUS_PREPARED: [STATUS_DISPATCHED, STATUS_CANCELLED],
    STATUS_DISPATCHED: [STATUS_DELIVERED],
    STATUS_DELIVERED: [],
    STATUS_CANCELLED: [],
}
STATUS_LABELS = {
    STATUS_PLACED: "Placed",
    STATUS_CONFIRMED: "Confirmed",
    STATUS_PREPARED: "Prepared",
    STATUS_DISPATCHED: "Out for delivery",
    STATUS_DELIVERED: "Delivered",
    STATUS_CANCELLED: "Cancelled",
}
STATUS_COLORS = {
    STATUS_PLACED: "secondary",
    STATUS_CONFIRMED: "info",
    STATUS_PREPARED: "warning",
    STATUS_DISPATCHED: "primary",
    STATUS_DELIVERED: "success",
    STATUS_CANCELLED: "danger",
}
STATUS_ICONS = {
    STATUS_PLACED: "receipt",
    STATUS_CONFIRMED: "check2-circle",
    STATUS_PREPARED: "egg-fried",
    STATUS_DISPATCHED: "bicycle",
    STATUS_DELIVERED: "house-check",
    STATUS_CANCELLED: "x-circle",
}
STATUS_PROGRESS = {
    STATUS_PLACED: 10,
    STATUS_CONFIRMED: 30,
    STATUS_PREPARED: 55,
    STATUS_DISPATCHED: 80,
    STATUS_DELIVERED: 100,
    STATUS_CANCELLED: 100,
}


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# users & profiles
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(24))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime)

    customer_profile = db.relationship(
        "CustomerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="CustomerProfile.user_id",
    )
    partner_profile = db.relationship(
        "DeliveryPartnerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="DeliveryPartnerProfile.user_id",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # -- password -----------------------------------------------------------
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password or "")

    # -- presentation -------------------------------------------------------
    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or self.username or "?").split() if p]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role.title())

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_customer(self) -> bool:
        return self.role == ROLE_CUSTOMER

    @property
    def is_delivery(self) -> bool:
        return self.role == ROLE_DELIVERY

    @property
    def dashboard_endpoint(self) -> str:
        return {
            ROLE_ADMIN: "admin.dashboard",
            ROLE_DELIVERY: "delivery.dashboard",
        }.get(self.role, "customer.dashboard")

    @property
    def unread_notifications(self) -> int:
        return self.notifications.filter_by(is_read=False).count()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} ({self.role})>"


class CustomerProfile(db.Model):
    __tablename__ = "customer_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    address = db.Column(db.String(255))
    city = db.Column(db.String(80))
    state = db.Column(db.String(80))
    pincode = db.Column(db.String(12))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    food_preferences = db.Column(db.Text)
    favorite_restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="customer_profile", foreign_keys=[user_id])
    favorite_restaurant = db.relationship("Restaurant", foreign_keys=[favorite_restaurant_id])

    @property
    def full_address(self) -> str:
        pieces = [self.address, self.city, self.state, self.pincode]
        return ", ".join(p for p in pieces if p) or "No address saved"

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def preference_list(self) -> list[str]:
        if not self.food_preferences:
            return []
        return [p.strip() for p in self.food_preferences.replace(";", ",").split(",") if p.strip()]


class DeliveryPartnerProfile(db.Model):
    __tablename__ = "delivery_partner_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(40), default="Bike")
    vehicle_number = db.Column(db.String(30))
    is_available = db.Column(db.Boolean, default=True, nullable=False, index=True)
    current_lat = db.Column(db.Float)
    current_lng = db.Column(db.Float)
    last_location_at = db.Column(db.DateTime)
    total_deliveries = db.Column(db.Integer, default=0, nullable=False)
    rating_avg = db.Column(db.Float, default=0.0, nullable=False)
    rating_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="partner_profile", foreign_keys=[user_id])

    @property
    def has_location(self) -> bool:
        return self.current_lat is not None and self.current_lng is not None

    @property
    def status_label(self) -> str:
        if not self.user.is_active:
            return "Inactive"
        return "Available" if self.is_available else "Busy"

    @property
    def status_color(self) -> str:
        if not self.user.is_active:
            return "secondary"
        return "success" if self.is_available else "warning"

    @property
    def active_order_count(self) -> int:
        return (
            Order.query.filter(
                Order.delivery_partner_id == self.user_id,
                Order.status.in_((STATUS_CONFIRMED, STATUS_PREPARED, STATUS_DISPATCHED)),
            ).count()
        )

    @property
    def rating_display(self) -> str:
        return f"{self.rating_avg:.1f}" if self.rating_count else "New"


# ---------------------------------------------------------------------------
# restaurants & menu
# ---------------------------------------------------------------------------
class Restaurant(db.Model):
    __tablename__ = "restaurants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False, index=True)
    description = db.Column(db.Text)
    cuisine = db.Column(db.String(80), index=True)
    address = db.Column(db.String(255))
    city = db.Column(db.String(80), index=True)
    phone = db.Column(db.String(24))
    email = db.Column(db.String(140))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    opening_time = db.Column(db.Time)
    closing_time = db.Column(db.Time)
    image_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    rating_avg = db.Column(db.Float, default=0.0, nullable=False)
    rating_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    menu_items = db.relationship(
        "MenuItem",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def is_open_now(self) -> bool:
        if not self.is_active:
            return False
        if not self.opening_time or not self.closing_time:
            return True
        now = datetime.now().time()
        if self.opening_time <= self.closing_time:
            return self.opening_time <= now <= self.closing_time
        # crosses midnight e.g. 11:00 -> 02:00
        return now >= self.opening_time or now <= self.closing_time

    @property
    def hours_label(self) -> str:
        if not self.opening_time or not self.closing_time:
            return "Hours not set"
        return f"{self.opening_time.strftime('%I:%M %p')} - {self.closing_time.strftime('%I:%M %p')}"

    @property
    def rating_display(self) -> str:
        return f"{self.rating_avg:.1f}" if self.rating_count else "New"

    @property
    def available_menu_count(self) -> int:
        return self.menu_items.filter_by(is_available=True).count()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Restaurant {self.name}>"


class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(60), default="Main Course", index=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    is_veg = db.Column(db.Boolean, default=True, nullable=False)
    prep_time_min = db.Column(db.Integer, default=20, nullable=False)
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    restaurant = db.relationship("Restaurant", back_populates="menu_items")

    @property
    def price_money(self) -> str:
        return format_money(self.price)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MenuItem {self.name}>"


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------
class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(24), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False, index=True)
    delivery_partner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    status = db.Column(db.String(20), default=STATUS_PLACED, nullable=False, index=True)
    payment_method = db.Column(db.String(30), default="COD")
    payment_status = db.Column(db.String(20), default="Pending")
    subtotal = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    delivery_fee = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    total = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    delivery_address = db.Column(db.String(255))
    delivery_lat = db.Column(db.Float)
    delivery_lng = db.Column(db.Float)
    distance_km = db.Column(db.Float, default=0.0)
    estimated_delivery_min = db.Column(db.Integer, default=30)
    notes = db.Column(db.String(500))

    placed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    confirmed_at = db.Column(db.DateTime)
    prepared_at = db.Column(db.DateTime)
    dispatched_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancellation_reason = db.Column(db.String(255))

    customer = db.relationship(
        "User", foreign_keys=[customer_id], backref=db.backref("customer_orders", lazy="dynamic")
    )
    delivery_partner = db.relationship(
        "User", foreign_keys=[delivery_partner_id], backref=db.backref("partner_orders", lazy="dynamic")
    )
    restaurant = db.relationship("Restaurant", backref=db.backref("orders", lazy="dynamic"))
    items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    feedback = db.relationship(
        "Feedback", back_populates="order", uselist=False, cascade="all, delete-orphan"
    )

    # -- presentation -------------------------------------------------------
    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.title())

    @property
    def status_color(self) -> str:
        return STATUS_COLORS.get(self.status, "secondary")

    @property
    def status_icon(self) -> str:
        return STATUS_ICONS.get(self.status, "circle")

    @property
    def progress_percent(self) -> int:
        return STATUS_PROGRESS.get(self.status, 0)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_delivered(self) -> bool:
        return self.status == STATUS_DELIVERED

    @property
    def is_cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED

    @property
    def can_cancel(self) -> bool:
        return self.status in (STATUS_PLACED, STATUS_CONFIRMED, STATUS_PREPARED)

    @property
    def can_be_rated(self) -> bool:
        return self.is_delivered and self.feedback is None

    @property
    def total_money(self) -> str:
        return format_money(self.total)

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def next_statuses(self) -> list[str]:
        return STATUS_FLOW.get(self.status, [])

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.next_statuses

    def set_status(self, new_status: str) -> bool:
        """Advance the order and stamp the matching timestamp."""
        if not self.can_transition_to(new_status):
            return False
        now = datetime.utcnow()
        self.status = new_status
        stamp_field = {
            STATUS_CONFIRMED: "confirmed_at",
            STATUS_PREPARED: "prepared_at",
            STATUS_DISPATCHED: "dispatched_at",
            STATUS_DELIVERED: "delivered_at",
            STATUS_CANCELLED: "cancelled_at",
        }.get(new_status)
        if stamp_field:
            setattr(self, stamp_field, now)
        if new_status == STATUS_DELIVERED:
            self.payment_status = "Paid" if self.payment_method != "COD" else "Collected"
            profile = self.delivery_partner.partner_profile if self.delivery_partner else None
            if profile:
                profile.total_deliveries += 1
        return True

    @property
    def timeline(self) -> list[dict]:
        steps = [
            ("Order placed", self.placed_at, "receipt"),
            ("Restaurant confirmed", self.confirmed_at, "check2-circle"),
            ("Food prepared", self.prepared_at, "egg-fried"),
            ("Out for delivery", self.dispatched_at, "bicycle"),
            ("Delivered", self.delivered_at, "house-check"),
        ]
        if self.is_cancelled:
            steps.append(("Cancelled", self.cancelled_at, "x-circle"))
        return [
            {
                "label": label,
                "at": at,
                "icon": icon,
                "done": at is not None,
                "current": at is not None and self.status != STATUS_DELIVERED,
            }
            for label, at, icon in steps
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.order_number} {self.status}>"


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"))
    item_name = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(60))
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total = db.Column(db.Numeric(10, 2), nullable=False)

    order = db.relationship("Order", back_populates="items")
    menu_item = db.relationship("MenuItem")

    @property
    def line_money(self) -> str:
        return format_money(self.line_total)


# ---------------------------------------------------------------------------
# tracking, notifications, feedback, settings
# ---------------------------------------------------------------------------
class LocationLog(db.Model):
    __tablename__ = "location_logs"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    speed_kmph = db.Column(db.Float)
    source = db.Column(db.String(30), default="gps")
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    order = db.relationship("Order", backref=db.backref("location_logs", lazy="dynamic"))
    partner = db.relationship("User", foreign_keys=[partner_id])


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(140), nullable=False)
    message = db.Column(db.String(500))
    category = db.Column(db.String(30), default="system")
    link = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="notifications")

    @property
    def icon(self) -> str:
        return {
            "order": "bag-check",
            "assignment": "bicycle",
            "system": "info-circle",
            "feedback": "star",
            "alert": "exclamation-triangle",
        }.get(self.category, "bell")


class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    restaurant_rating = db.Column(db.Integer, nullable=False)
    partner_rating = db.Column(db.Integer)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    order = db.relationship("Order", back_populates="feedback")
    customer = db.relationship("User", foreign_keys=[customer_id])
    restaurant = db.relationship("Restaurant", backref=db.backref("feedbacks", lazy="dynamic"))
    partner = db.relationship("User", foreign_keys=[partner_id])


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemSetting {self.key}={self.value}>"


class AuditLog(db.Model):
    """Admin action audit trail (SRS 3.13). Append-only - rows are never
    edited from the UI; every administrator mutation writes one entry."""

    __tablename__ = "admin_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    admin_name = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    target = db.Column(db.String(80))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
