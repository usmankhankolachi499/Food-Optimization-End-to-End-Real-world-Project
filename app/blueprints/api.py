"""JSON API used by the live tracking map, notifications and mobile clients."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import get_current_user, login_required
from ..extensions import db, text
from ..models import (
    ROLE_DELIVERY,
    Notification,
    Order,
)
from ..services import routing
from ..services.tracking import record_location, tracking_payload
from ..utils import is_lat, is_lng, to_int, utcnow

bp = Blueprint("api", __name__)


def _authorize_order(order_id: int):
    user = get_current_user()
    if user is None:
        return None, (jsonify({"ok": False, "error": "Authentication required"}), 401)
    order = db.session.get(Order, order_id)
    if order is None:
        return None, (jsonify({"ok": False, "error": "Order not found"}), 404)
    if user.is_admin or order.customer_id == user.id or order.delivery_partner_id == user.id:
        return order, None
    return None, (jsonify({"ok": False, "error": "You cannot view this order"}), 403)


@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"ok": True, "service": "food-delivery", "time": utcnow().isoformat() + "Z"})
    except Exception as exc:  # pragma: no cover
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp.get("/orders/<int:order_id>/tracking")
@login_required
def order_tracking(order_id):
    order, error = _authorize_order(order_id)
    if error:
        return error
    return jsonify(tracking_payload(order))


@bp.get("/orders/<int:order_id>/route")
@login_required
def order_route(order_id):
    order, error = _authorize_order(order_id)
    if error:
        return error
    profile = order.delivery_partner.partner_profile if order.delivery_partner else None
    return jsonify({"ok": True, "route": routing.route_for_order(order, profile)})


@bp.post("/partners/location")
@login_required
def partner_location():
    user = get_current_user()
    if user.role != ROLE_DELIVERY:
        return jsonify({"ok": False, "error": "Only delivery partners can push locations"}), 403
    payload = request.get_json(silent=True) or request.form
    lat = payload.get("latitude") or payload.get("lat")
    lng = payload.get("longitude") or payload.get("lng")
    if not (is_lat(lat) and is_lng(lng)):
        return jsonify({"ok": False, "error": "Invalid latitude/longitude"}), 400

    order_id = to_int(payload.get("order_id"), 0) or None
    order = None
    if order_id:
        order = db.session.get(Order, order_id)
        if order is None or order.delivery_partner_id != user.id:
            return jsonify({"ok": False, "error": "Order is not assigned to you"}), 403

    record_location(
        user.id,
        lat,
        lng,
        order_id=order_id,
        speed_kmph=payload.get("speed"),
        source="api",
    )
    db.session.commit()
    result = {
        "ok": True,
        "message": "Location recorded",
        "lat": float(lat),
        "lng": float(lng),
        "at": utcnow().isoformat() + "Z",
    }
    if order is not None:
        result["order"] = tracking_payload(order)
    return jsonify(result)


@bp.get("/notifications")
@login_required
def notifications():
    user = get_current_user()
    rows = (
        Notification.query.filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .limit(12)
        .all()
    )
    return jsonify(
        {
            "ok": True,
            "unread": Notification.query.filter_by(user_id=user.id, is_read=False).count(),
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "message": row.message,
                    "category": row.category,
                    "icon": row.icon,
                    "link": row.link,
                    "is_read": row.is_read,
                    "created_at": row.created_at.isoformat() + "Z",
                }
                for row in rows
            ],
        }
    )


@bp.post("/notifications/read")
@login_required
def notifications_read():
    user = get_current_user()
    payload = request.get_json(silent=True) or request.form
    notification_id = to_int(payload.get("id"), 0)
    if str(payload.get("all", "")).lower() in {"1", "true", "yes", "on"} or not notification_id:
        Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    else:
        row = Notification.query.filter_by(id=notification_id, user_id=user.id).first()
        if row is None:
            return jsonify({"ok": False, "error": "Notification not found"}), 404
        row.is_read = True
    db.session.commit()
    return jsonify({"ok": True, "unread": Notification.query.filter_by(user_id=user.id, is_read=False).count()})
