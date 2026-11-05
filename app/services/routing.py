"""Route optimization and ETA calculation.

The SRS asks for shortest/fastest routes, traffic awareness and dynamic
recalculation. This module implements a nearest-neighbour optimizer with
pickup-before-drop precedence for batched orders. Travel time uses the
traffic multiplier and average speed configured in Admin > Settings. If the
separately-built ML module provides an ETA predictor, :mod:`ml_bridge` is
used for the final estimate.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from ..models import Order
from ..utils import haversine_km
from .ml_bridge import predict_eta
from .settings import get_float


def _coord(entity) -> Optional[tuple[float, float]]:
    lat = getattr(entity, "latitude", None)
    lng = getattr(entity, "longitude", None)
    if lat is None or lng is None:
        lat = getattr(entity, "delivery_lat", None)
        lng = getattr(entity, "delivery_lng", None)
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def travel_minutes(distance_km: float, traffic_factor: float | None = None) -> int:
    speed = max(8.0, get_float("avg_speed_kmph", 24.0))
    traffic_factor = (
        float(traffic_factor) if traffic_factor is not None else get_float("traffic_factor", 1.15)
    )
    return max(1, int(round((max(0.0, distance_km) / speed) * 60 * max(1.0, traffic_factor))))


def estimate_eta(order: Order, prep_time_min: int | None = None) -> int:
    """Estimated minutes from now until delivery for one order."""
    items = list(order.items)
    item_prep = max((item.menu_item.prep_time_min for item in items if item.menu_item), default=20)
    prep = max(prep_time_min or 0, item_prep)
    distance = float(order.distance_km or 0)
    result = predict_eta(
        distance_km=distance,
        prep_time_min=prep,
        item_count=order.item_count or 1,
        traffic_factor=get_float("traffic_factor", 1.15),
        hour_of_day=order.placed_at.hour if order.placed_at else None,
    )
    return int(result["minutes"])


def _route_from_points(points: list[dict]) -> list[dict]:
    """Order points with nearest-neighbour, keeping the first point fixed."""
    if len(points) <= 2:
        return points
    ordered = [points[0]]
    remaining = points[1:]
    while remaining:
        current = ordered[-1]
        best_index = min(
            range(len(remaining)),
            key=lambda i: haversine_km(
                current.get("lat"), current.get("lng"),
                remaining[i].get("lat"), remaining[i].get("lng"),
            ),
        )
        ordered.append(remaining.pop(best_index))
    return ordered


def route_for_order(order: Order, partner_profile=None) -> dict[str, Any]:
    """Partner -> restaurant -> customer route for the tracking screen."""
    points: list[dict] = []
    if partner_profile and partner_profile.has_location:
        points.append(
            {
                "kind": "partner",
                "label": "Your location",
                "lat": partner_profile.current_lat,
                "lng": partner_profile.current_lng,
            }
        )
    if order.restaurant and order.restaurant.has_location:
        points.append(
            {
                "kind": "restaurant",
                "label": order.restaurant.name,
                "lat": order.restaurant.latitude,
                "lng": order.restaurant.longitude,
            }
        )
    if order.delivery_lat is not None and order.delivery_lng is not None:
        points.append(
            {
                "kind": "customer",
                "label": "Delivery address",
                "lat": order.delivery_lat,
                "lng": order.delivery_lng,
            }
        )

    distance = 0.0
    for first, second in zip(points, points[1:]):
        distance += haversine_km(first["lat"], first["lng"], second["lat"], second["lng"])
    distance = round(distance, 2)
    return {
        "points": points,
        "distance_km": distance,
        "eta_minutes": travel_minutes(distance),
        "order_number": order.order_number,
    }


def optimize_batch(orders: Iterable[Order], partner_profile=None) -> dict[str, Any]:
    """Optimize a multi-order route with pickup-before-delivery precedence."""
    orders = [o for o in orders if o is not None]
    start: Optional[dict] = None
    if partner_profile and partner_profile.has_location:
        start = {
            "kind": "partner",
            "label": "Start",
            "lat": partner_profile.current_lat,
            "lng": partner_profile.current_lng,
            "order_id": None,
        }

    stops: list[dict] = []
    for order in orders:
        restaurant = order.restaurant
        if restaurant and restaurant.has_location:
            stops.append(
                {
                    "kind": "pickup",
                    "label": f"Pickup: {restaurant.name}",
                    "address": restaurant.address,
                    "lat": restaurant.latitude,
                    "lng": restaurant.longitude,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }
            )
        if order.delivery_lat is not None and order.delivery_lng is not None:
            stops.append(
                {
                    "kind": "drop",
                    "label": f"Deliver: {order.order_number}",
                    "address": order.delivery_address,
                    "lat": order.delivery_lat,
                    "lng": order.delivery_lng,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }
            )

    if not stops:
        return {
            "stops": [],
            "distance_km": 0,
            "eta_minutes": 0,
            "skipped_orders": [o.order_number for o in orders],
            "pickup_done": [],
        }

    if start is None:
        # Start from the first pickup instead of an unknown partner location.
        first_pickup = next((s for s in stops if s["kind"] == "pickup"), stops[0])
        start = {
            "kind": "partner",
            "label": "Start",
            "lat": first_pickup["lat"],
            "lng": first_pickup["lng"],
            "order_id": None,
        }

    pending = list(stops)
    ordered: list[dict] = [start]
    picked_up: set[int] = set()
    distance = 0.0
    while pending:
        current = ordered[-1]
        eligible = [
            stop
            for stop in pending
            if stop["kind"] == "pickup" or stop["order_id"] in picked_up
        ]
        if not eligible:  # safety net (shouldn't happen)
            eligible = pending
        next_stop = min(
            eligible,
            key=lambda stop: haversine_km(
                current["lat"], current["lng"], stop["lat"], stop["lng"]
            ),
        )
        leg = haversine_km(
            current["lat"], current["lng"], next_stop["lat"], next_stop["lng"]
        )
        distance += leg
        next_stop = dict(next_stop, leg_km=round(leg, 2))
        ordered.append(next_stop)
        pending.remove(next_stop if next_stop in pending else next(
            s for s in pending if s["order_id"] == next_stop["order_id"] and s["kind"] == next_stop["kind"]
        ))
        if next_stop["kind"] == "pickup":
            picked_up.add(next_stop["order_id"])

    # Number only the real stops (skip the synthetic start).
    for index, stop in enumerate(ordered[1:], start=1):
        stop["sequence"] = index

    distance = round(distance, 2)
    return {
        "stops": ordered,
        "distance_km": distance,
        "eta_minutes": travel_minutes(distance),
        "skipped_orders": [
            o.order_number
            for o in orders
            if not (o.restaurant and o.restaurant.has_location)
            and (o.delivery_lat is None or o.delivery_lng is None)
        ],
        "pickup_done": sorted(picked_up),
    }
