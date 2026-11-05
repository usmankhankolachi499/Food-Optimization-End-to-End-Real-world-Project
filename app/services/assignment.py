"""Order assignment (SRS: nearest available partner + workload + batching)."""
from __future__ import annotations

from typing import Optional

from flask import url_for

from ..extensions import db
from ..models import (
    ACTIVE_STATUSES,
    ROLE_DELIVERY,
    DeliveryPartnerProfile,
    Order,
    User,
)
from ..utils import haversine_km
from .ml_bridge import predict_partner_score
from .notifications import notify, notify_admins
from .settings import get_bool, get_float, get_int


def partner_workload(partner_id: int) -> int:
    return Order.query.filter(
        Order.delivery_partner_id == partner_id,
        Order.status.in_(ACTIVE_STATUSES),
    ).count()


def _distance_to_pickup(profile: DeliveryPartnerProfile, order: Order) -> Optional[float]:
    if not profile.has_location or not order.restaurant or not order.restaurant.has_location:
        return None
    return haversine_km(
        profile.current_lat,
        profile.current_lng,
        order.restaurant.latitude,
        order.restaurant.longitude,
    )


def ranked_partners(order: Order) -> list[dict]:
    """All active partners ranked by distance, workload and optional ML score."""
    max_orders = max(1, get_int("max_orders_per_partner", 3))
    radius = max(0.0, get_float("max_delivery_radius_km", 12.0))
    profiles = (
        DeliveryPartnerProfile.query.join(User)
        .filter(User.role == ROLE_DELIVERY, User.is_active.is_(True))
        .all()
    )
    ranked: list[dict] = []
    for profile in profiles:
        workload = partner_workload(profile.user_id)
        distance = _distance_to_pickup(profile, order)
        score = predict_partner_score(distance or 0, workload, profile.rating_avg)
        reasons = []
        if not profile.is_available:
            reasons.append("unavailable")
        if workload >= max_orders:
            reasons.append(f"at capacity ({workload}/{max_orders})")
        if distance is None:
            reasons.append("location unknown")
        elif radius and distance > radius:
            reasons.append(f"outside {radius:.0f} km radius")
        if score is None:
            # deterministic: distance dominates, workload breaks ties
            score = (distance if distance is not None else 999.0) + workload * 2.0
        ranked.append(
            {
                "partner": profile.user,
                "profile": profile,
                "distance_km": distance,
                "workload": workload,
                "score": round(float(score), 3),
                "eligible": not reasons,
                "reasons": reasons,
            }
        )
    ranked.sort(key=lambda row: (not row["eligible"], row["score"], row["distance_km"] or 999))
    return ranked


def best_partner(order: Order) -> Optional[dict]:
    for row in ranked_partners(order):
        if row["eligible"]:
            return row
    return None


def assign_order(
    order: Order,
    partner: User,
    actor: str = "system",
    force: bool = False,
) -> tuple[bool, str]:
    """Assign (or reassign) a partner to an order. Caller commits the session."""
    if partner is None or partner.role != ROLE_DELIVERY:
        return False, "Select a valid delivery partner."
    if not partner.is_active:
        return False, "That delivery partner account is inactive."
    if order.status not in ACTIVE_STATUSES:
        return False, "Only active orders can be assigned."
    if order.delivery_partner_id == partner.id:
        return True, "Order is already assigned to this partner."
    if order.delivery_partner_id and not force:
        return False, "Order already has a delivery partner. Use reassign to override."

    profile = partner.partner_profile
    workload = partner_workload(partner.id)
    max_orders = max(1, get_int("max_orders_per_partner", 3))
    if not force:
        if profile is None or not profile.is_available:
            return False, "Delivery partner is currently unavailable."
        if workload >= max_orders:
            return False, f"Delivery partner already has {workload} active order(s)."

    order.delivery_partner_id = partner.id
    link = url_for("delivery.order_detail", order_id=order.id)
    notify(
        partner.id,
        "New delivery assignment",
        f"{order.order_number} from {order.restaurant.name} ({order.delivery_address}).",
        "assignment",
        link,
    )
    notify(
        order.customer_id,
        "Delivery partner assigned",
        f"{partner.name} will deliver {order.order_number}.",
        "order",
        url_for("customer.order_detail", order_id=order.id),
    )
    return True, f"Assigned to {partner.name}."


def auto_assign_order(order: Order, actor: str = "system", force: bool = False) -> Optional[User]:
    """Assign the best available partner, if automatic assignment is enabled.

    ``force=True`` is used by the administrator's explicit "auto-assign"
    action, which should work even when automatic dispatch on checkout is off.
    """
    if order.delivery_partner_id or order.status not in ACTIVE_STATUSES:
        return order.delivery_partner if order.delivery_partner_id else None
    if not force and not get_bool("auto_assign_orders", True):
        return None
    candidate = best_partner(order)
    if not candidate:
        notify_admins(
            "No delivery partner available",
            f"{order.order_number} is waiting for a partner. Assign manually from Orders.",
            "alert",
            url_for("admin.order_detail", order_id=order.id),
        )
        return None
    success, _ = assign_order(order, candidate["partner"], actor=actor)
    return candidate["partner"] if success else None


def unassign_order(order: Order, actor: str = "system") -> None:
    if not order.delivery_partner_id:
        return
    previous = order.delivery_partner
    order.delivery_partner_id = None
    if previous:
        notify(
            previous.id,
            "Assignment removed",
            f"{order.order_number} is no longer assigned to you.",
            "assignment",
            url_for("delivery.dashboard"),
        )


def open_assignments_for(partner: User, limit: int = 20) -> list[Order]:
    """Unassigned active orders, nearest-first from the partner's location."""
    profile = partner.partner_profile
    radius = max(0.0, get_float("max_delivery_radius_km", 12.0))
    orders = (
        Order.query.filter(
            Order.delivery_partner_id.is_(None),
            Order.status.in_((  # placed orders are auto-confirmed at checkout
                "confirmed",
                "prepared",
            )),
        )
        .order_by(Order.placed_at.asc())
        .limit(100)
        .all()
    )
    rows: list[tuple[float, Order]] = []
    for order in orders:
        distance = None
        if profile and profile.has_location and order.restaurant and order.restaurant.has_location:
            distance = haversine_km(
                profile.current_lat,
                profile.current_lng,
                order.restaurant.latitude,
                order.restaurant.longitude,
            )
        if distance is not None and radius and distance > radius:
            continue
        rows.append((distance if distance is not None else 999.0, order))
    rows.sort(key=lambda item: item[0])
    return [order for _, order in rows[:limit]]


def partner_active_orders(partner: User) -> list[Order]:
    return (
        Order.query.filter(
            Order.delivery_partner_id == partner.id,
            Order.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Order.placed_at.asc())
        .all()
    )
