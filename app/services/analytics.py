"""Analytics & reporting (SRS: delivery time, trends, partner performance)."""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Iterable, Optional

from ..models import (
    ACTIVE_STATUSES,
    ROLE_DELIVERY,
    DeliveryPartnerProfile,
    Feedback,
    Order,
    Restaurant,
    User,
)
from ..utils import utcnow

ZERO = Decimal("0.00")


def period_start(days: int):
    return utcnow() - timedelta(days=max(1, int(days)))


def orders_in_period(days: int, statuses: Optional[Iterable[str]] = None) -> list[Order]:
    query = Order.query.filter(Order.placed_at >= period_start(days))
    if statuses:
        query = query.filter(Order.status.in_(list(statuses)))
    return query.order_by(Order.placed_at.asc()).all()


def delivery_minutes(order: Order) -> Optional[float]:
    if not order.delivered_at:
        return None
    start = order.dispatched_at or order.confirmed_at or order.placed_at
    if not start:
        return None
    return max(0.0, (order.delivered_at - start).total_seconds() / 60.0)


def prep_minutes(order: Order) -> Optional[float]:
    if not order.prepared_at:
        return None
    start = order.confirmed_at or order.placed_at
    if not start:
        return None
    return max(0.0, (order.prepared_at - start).total_seconds() / 60.0)


def summary(days: int = 30) -> dict:
    orders = orders_in_period(days)
    delivered = [o for o in orders if o.status == "delivered"]
    cancelled = [o for o in orders if o.status == "cancelled"]
    active = [o for o in orders if o.status in ACTIVE_STATUSES]
    revenue = sum((o.total or ZERO for o in delivered), ZERO)
    times = [t for t in (delivery_minutes(o) for o in delivered) if t is not None]
    preps = [t for t in (prep_minutes(o) for o in delivered) if t is not None]
    ratings = [
        f.restaurant_rating
        for f in Feedback.query.filter(Feedback.created_at >= period_start(days)).all()
    ]
    total_non_cancelled = max(1, len(orders) - len(cancelled))
    return {
        "total_orders": len(orders),
        "delivered_orders": len(delivered),
        "active_orders": len(active),
        "cancelled_orders": len(cancelled),
        "revenue": round(float(revenue), 2),
        "avg_order_value": round(float(revenue) / len(delivered), 2) if delivered else 0.0,
        "avg_delivery_min": round(sum(times) / len(times), 1) if times else 0.0,
        "avg_prep_min": round(sum(preps) / len(preps), 1) if preps else 0.0,
        "completion_rate": round(len(delivered) / total_non_cancelled * 100, 1),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0.0,
        "feedback_count": len(ratings),
    }


def daily_trend(days: int = 14) -> dict:
    days = max(2, int(days))
    start = utcnow().date() - timedelta(days=days - 1)
    buckets = {
        start + timedelta(days=offset): {"orders": 0, "revenue": 0.0, "delivered": 0}
        for offset in range(days)
    }
    for order in orders_in_period(days + 1):
        key = order.placed_at.date() if order.placed_at else None
        if key not in buckets:
            continue
        buckets[key]["orders"] += 1
        if order.status == "delivered":
            buckets[key]["delivered"] += 1
            buckets[key]["revenue"] += float(order.total or 0)
    labels = [day.strftime("%d %b") for day in buckets]
    return {
        "labels": labels,
        "orders": [b["orders"] for b in buckets.values()],
        "revenue": [round(b["revenue"], 2) for b in buckets.values()],
        "delivered": [b["delivered"] for b in buckets.values()],
    }


def peak_hours(days: int = 30) -> dict:
    counts = Counter({hour: 0 for hour in range(24)})
    for order in orders_in_period(days):
        if order.placed_at:
            counts[order.placed_at.hour] += 1
    labels = [f"{hour:02d}:00" for hour in range(24)]
    return {
        "labels": labels,
        "values": [counts[hour] for hour in range(24)],
        "busiest_hour": max(counts, key=counts.get) if any(counts.values()) else None,
    }


def status_distribution(days: int = 30) -> dict:
    counts = Counter(o.status for o in orders_in_period(days))
    order = ["placed", "confirmed", "prepared", "dispatched", "delivered", "cancelled"]
    labels = [status.replace("_", " ").title() for status in order]
    values = [counts.get(status, 0) for status in order]
    colors = ["#9aa3b5", "#d4af6a", "#f59e0b", "#151e2d", "#2e7d5b", "#ef4444"]
    return {"labels": labels, "values": values, "colors": colors}


def top_restaurants(days: int = 30, limit: int = 6) -> list[dict]:
    rows = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    for order in orders_in_period(days):
        rows[order.restaurant_id]["orders"] += 1
        if order.status == "delivered":
            rows[order.restaurant_id]["revenue"] += float(order.total or 0)
    restaurants = {r.id: r for r in Restaurant.query.filter(Restaurant.id.in_(rows.keys())).all()}
    result = []
    for restaurant_id, stats in rows.items():
        restaurant = restaurants.get(restaurant_id)
        if not restaurant:
            continue
        result.append(
            {
                "restaurant": restaurant,
                "orders": stats["orders"],
                "revenue": round(stats["revenue"], 2),
                "rating": restaurant.rating_avg,
            }
        )
    result.sort(key=lambda row: (row["orders"], row["revenue"]), reverse=True)
    return result[:limit]


def partner_performance(days: int = 30, limit: Optional[int] = None) -> list[dict]:
    start = period_start(days)
    profiles = (
        DeliveryPartnerProfile.query.join(User)
        .filter(User.role == ROLE_DELIVERY)
        .order_by(User.name.asc())
        .all()
    )
    rows = []
    for profile in profiles:
        delivered = (
            Order.query.filter(
                Order.delivery_partner_id == profile.user_id,
                Order.status == "delivered",
                Order.delivered_at >= start,
            )
            .order_by(Order.delivered_at.asc())
            .all()
        )
        times = [t for t in (delivery_minutes(o) for o in delivered) if t is not None]
        earnings = sum(float(o.delivery_fee or 0) for o in delivered)
        rows.append(
            {
                "profile": profile,
                "partner": profile.user,
                "deliveries": len(delivered),
                "avg_delivery_min": round(sum(times) / len(times), 1) if times else 0.0,
                "earnings": round(earnings, 2),
                "rating": profile.rating_avg,
                "rating_count": profile.rating_count,
                "active": profile.active_order_count,
                "total_deliveries": profile.total_deliveries,
            }
        )
    rows.sort(key=lambda row: (row["deliveries"], row["rating"]), reverse=True)
    return rows[:limit] if limit else rows


def partner_stats(partner: User, days: int = 30) -> dict:
    start = period_start(days)
    assigned = Order.query.filter(
        Order.delivery_partner_id == partner.id,
        Order.placed_at >= start,
    ).all()
    delivered = [o for o in assigned if o.status == "delivered"]
    times = [t for t in (delivery_minutes(o) for o in delivered) if t is not None]
    earnings = sum(float(o.delivery_fee or 0) for o in delivered)
    today = utcnow().date()
    today_delivered = [o for o in delivered if o.delivered_at and o.delivered_at.date() == today]
    return {
        "assigned": len(assigned),
        "delivered": len(delivered),
        "today_delivered": len(today_delivered),
        "active": partner.partner_profile.active_order_count if partner.partner_profile else 0,
        "avg_delivery_min": round(sum(times) / len(times), 1) if times else 0.0,
        "earnings": round(earnings, 2),
        "rating": partner.partner_profile.rating_avg if partner.partner_profile else 0.0,
        "rating_count": partner.partner_profile.rating_count if partner.partner_profile else 0,
        "total_deliveries": partner.partner_profile.total_deliveries if partner.partner_profile else 0,
    }


def customer_stats(customer: User) -> dict:
    orders = Order.query.filter_by(customer_id=customer.id).all()
    delivered = [o for o in orders if o.status == "delivered"]
    active = [o for o in orders if o.status in ACTIVE_STATUSES]
    spent = sum((o.total or ZERO for o in delivered), ZERO)
    return {
        "orders": len(orders),
        "active": len(active),
        "delivered": len(delivered),
        "spent": round(float(spent), 2),
    }


def restaurant_stats(restaurant: Restaurant, days: int = 30) -> dict:
    orders = Order.query.filter(
        Order.restaurant_id == restaurant.id,
        Order.placed_at >= period_start(days),
    ).all()
    delivered = [o for o in orders if o.status == "delivered"]
    return {
        "orders": len(orders),
        "delivered": len(delivered),
        "revenue": round(sum(float(o.total or 0) for o in delivered), 2),
        "rating": restaurant.rating_avg,
        "rating_count": restaurant.rating_count,
    }


def analytics_bundle(days: int = 30) -> dict:
    trend = daily_trend(min(14, max(7, days)))
    peak = peak_hours(days)
    statuses = status_distribution(days)
    restaurants = top_restaurants(days, limit=6)
    partners = partner_performance(days, limit=8)
    return {
        "days": days,
        "summary": summary(days),
        "trend": trend,
        "peak": peak,
        "statuses": statuses,
        "top_restaurants": restaurants,
        "partners": partners,
        # JSON-safe payload consumed by charts.js on the analytics page.
        "chart": {
            "trend": trend,
            "peak": peak,
            "statuses": statuses,
            "top_restaurants": [
                {"restaurant": {"name": row["restaurant"].name}, "orders": row["orders"]}
                for row in restaurants
            ],
        },
    }


# ---------------------------------------------------------------------------
# CSV reports (SRS: generate reports)
# ---------------------------------------------------------------------------
def orders_csv(days: int = 30) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Order Number", "Placed At", "Customer", "Restaurant", "Partner",
            "Status", "Payment", "Subtotal", "Delivery Fee", "Total",
            "Distance (km)", "Delivery Minutes",
        ]
    )
    for order in orders_in_period(days):
        writer.writerow(
            [
                order.order_number,
                order.placed_at.strftime("%Y-%m-%d %H:%M") if order.placed_at else "",
                order.customer.name if order.customer else "",
                order.restaurant.name if order.restaurant else "",
                order.delivery_partner.name if order.delivery_partner else "Unassigned",
                order.status_label,
                order.payment_status,
                float(order.subtotal or 0),
                float(order.delivery_fee or 0),
                float(order.total or 0),
                round(float(order.distance_km or 0), 2),
                round(delivery_minutes(order) or 0, 1),
            ]
        )
    return buffer.getvalue()


def partners_csv(days: int = 30) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Partner", "Email", "Phone", "Vehicle", "Status", "Deliveries (period)",
            "Avg Delivery Minutes", "Rating", "Ratings", "Earnings (period)",
        ]
    )
    for row in partner_performance(days):
        profile = row["profile"]
        partner = row["partner"]
        writer.writerow(
            [
                partner.name,
                partner.email,
                partner.phone or "",
                f"{profile.vehicle_type or ''} {profile.vehicle_number or ''}".strip(),
                profile.status_label,
                row["deliveries"],
                row["avg_delivery_min"],
                round(profile.rating_avg, 2),
                profile.rating_count,
                row["earnings"],
            ]
        )
    return buffer.getvalue()
