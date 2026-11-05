"""Real-time location tracking.

Relational ``LocationLog`` rows are the canonical store (works everywhere).
When ``MONGO_URI`` is configured *and* ``pymongo`` is installed, every point
is also mirrored to MongoDB, matching the SRS storage split for high-volume
tracking data.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from flask import current_app

from ..extensions import db
from ..models import LocationLog, Order
from ..utils import is_lat, is_lng, utcnow

log = logging.getLogger(__name__)

_mongo_client = None
_mongo_failed = False


def _mongo_collection():
    global _mongo_client, _mongo_failed
    uri = current_app.config.get("MONGO_URI", "")
    if not uri or _mongo_failed:
        return None
    try:
        from pymongo import MongoClient  # optional dependency

        if _mongo_client is None:
            _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=1200)
        db_name = current_app.config.get("MONGO_DB", "food_delivery")
        collection = current_app.config.get("MONGO_COLLECTION", "location_logs")
        return _mongo_client[db_name][collection]
    except Exception as exc:  # pragma: no cover - depends on optional service
        _mongo_failed = True
        log.info("MongoDB tracking disabled: %s", exc)
        return None


def mongo_enabled() -> bool:
    return _mongo_collection() is not None


def record_location(
    partner_id: int,
    latitude,
    longitude,
    order_id: Optional[int] = None,
    speed_kmph: Optional[float] = None,
    source: str = "gps",
) -> Optional[LocationLog]:
    """Persist a location point and update the partner's current position."""
    if not (is_lat(latitude) and is_lng(longitude)):
        return None
    lat, lng = float(latitude), float(longitude)
    row = LocationLog(
        order_id=order_id,
        partner_id=partner_id,
        latitude=lat,
        longitude=lng,
        speed_kmph=float(speed_kmph) if speed_kmph is not None else None,
        source=source,
        recorded_at=utcnow(),
    )
    db.session.add(row)

    from ..models import DeliveryPartnerProfile

    profile = DeliveryPartnerProfile.query.filter_by(user_id=partner_id).first()
    if profile is not None:
        profile.current_lat = lat
        profile.current_lng = lng
        profile.last_location_at = row.recorded_at

    collection = _mongo_collection()
    if collection is not None:
        try:
            collection.insert_one(
                {
                    "partner_id": partner_id,
                    "order_id": order_id,
                    "latitude": lat,
                    "longitude": lng,
                    "speed_kmph": row.speed_kmph,
                    "source": source,
                    "recorded_at": datetime.utcnow(),
                }
            )
        except Exception as exc:  # pragma: no cover
            log.warning("MongoDB location insert failed: %s", exc)
    return row


def get_track(order_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        LocationLog.query.filter_by(order_id=order_id)
        .order_by(LocationLog.recorded_at.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    if rows:
        return [
            {
                "lat": row.latitude,
                "lng": row.longitude,
                "speed": row.speed_kmph,
                "source": row.source,
                "at": row.recorded_at.isoformat() + "Z",
            }
            for row in rows
        ]

    # Mongo fallback for deployments that only keep high-volume logs there.
    collection = _mongo_collection()
    if collection is not None:
        try:
            cursor = (
                collection.find({"order_id": order_id})
                .sort("recorded_at", 1)
                .limit(limit)
            )
            return [
                {
                    "lat": doc.get("latitude"),
                    "lng": doc.get("longitude"),
                    "speed": doc.get("speed_kmph"),
                    "source": doc.get("source", "gps"),
                    "at": doc.get("recorded_at").isoformat() + "Z"
                    if isinstance(doc.get("recorded_at"), datetime)
                    else None,
                }
                for doc in cursor
            ]
        except Exception as exc:  # pragma: no cover
            log.warning("MongoDB tracking query failed: %s", exc)
    return []


def tracking_payload(order: Order) -> dict[str, Any]:
    """Everything the customer/partner map needs in a single response."""
    partner = order.delivery_partner
    profile = partner.partner_profile if partner else None
    track = get_track(order.id, limit=80)
    latest = track[-1] if track else None
    if profile and profile.has_location:
        latest = {
            "lat": profile.current_lat,
            "lng": profile.current_lng,
            "at": profile.last_location_at.isoformat() + "Z"
            if profile.last_location_at
            else None,
            "source": "profile",
        }

    return {
        "ok": True,
        "order": {
            "id": order.id,
            "number": order.order_number,
            "status": order.status,
            "status_label": order.status_label,
            "progress": order.progress_percent,
            "updated_at": order.placed_at.isoformat() + "Z" if order.placed_at else None,
        },
        "restaurant": {
            "name": order.restaurant.name,
            "lat": order.restaurant.latitude,
            "lng": order.restaurant.longitude,
            "address": order.restaurant.address,
        },
        "destination": {
            "address": order.delivery_address,
            "lat": order.delivery_lat,
            "lng": order.delivery_lng,
        },
        "partner": {
            "name": partner.name if partner else None,
            "phone": partner.phone if partner else None,
            "lat": profile.current_lat if profile else None,
            "lng": profile.current_lng if profile else None,
            "last_seen": profile.last_location_at.isoformat() + "Z"
            if profile and profile.last_location_at
            else None,
        },
        "latest": latest,
        "track": track,
        "mongo": mongo_enabled(),
    }
