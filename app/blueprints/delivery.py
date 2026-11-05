"""Delivery partner area: assignments, live location, deliveries, earnings."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from ..auth import get_current_user, login_required
from ..extensions import db
from ..models import (
    ROLE_DELIVERY,
    STATUS_CONFIRMED,
    STATUS_DELIVERED,
    STATUS_DISPATCHED,
    STATUS_PREPARED,
    DeliveryPartnerProfile,
    Order,
)
from ..services import analytics, routing
from ..services.assignment import (
    assign_order,
    open_assignments_for,
    partner_active_orders,
)
from ..services.notifications import notify, notify_order_status
from ..services.settings import get_float
from ..services.tracking import record_location, tracking_payload
from ..utils import (
    haversine_km,
    is_lat,
    is_lng,
    utcnow,
    validate_phone,
)

bp = Blueprint("delivery", __name__)


def _user():
    return get_current_user()


def _profile() -> DeliveryPartnerProfile:
    user = _user()
    profile = user.partner_profile
    if profile is None:
        profile = DeliveryPartnerProfile(user_id=user.id)
        db.session.add(profile)
        db.session.commit()
    return profile


@bp.before_request
def _guard():
    user = _user()
    if user is None:
        return None
    if user.role != ROLE_DELIVERY:
        abort(403)
    return None


def _assigned_order(order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, delivery_partner_id=_user().id).first()
    if order is None:
        abort(404)
    return order


# ---------------------------------------------------------------------------
# dashboard & assignments
# ---------------------------------------------------------------------------
@bp.get("/dashboard")
@login_required
def dashboard():
    user = _user()
    profile = _profile()
    stats = analytics.partner_stats(user)
    active = partner_active_orders(user)
    open_jobs = open_assignments_for(user, limit=6)
    route = routing.optimize_batch(active, profile) if active else {
        "stops": [],
        "distance_km": 0,
        "eta_minutes": 0,
    }
    return render_template(
        "delivery/dashboard.html",
        profile=profile,
        stats=stats,
        active_orders=active,
        open_jobs=open_jobs,
        route=route,
    )


@bp.get("/assignments")
@login_required
def assignments():
    user = _user()
    return render_template(
        "delivery/assignments.html",
        open_jobs=open_assignments_for(user, limit=30),
        active_orders=partner_active_orders(user),
        profile=_profile(),
    )


@bp.post("/assignments/<int:order_id>/accept")
@login_required
def accept_assignment(order_id):
    user = _user()
    profile = _profile()
    order = db.session.get(Order, order_id)
    if order is None or order.status in ("delivered", "cancelled"):
        abort(404)

    if order.delivery_partner_id not in (None, user.id):
        flash("That order has already been taken by another partner.", "warning")
        return redirect(url_for("delivery.assignments"))

    if order.delivery_partner_id is None:
        # radius guard for direct accept
        radius = get_float("max_delivery_radius_km", 12.0)
        if profile.has_location and order.restaurant and order.restaurant.has_location:
            distance = haversine_km(
                profile.current_lat,
                profile.current_lng,
                order.restaurant.latitude,
                order.restaurant.longitude,
            )
            if radius and distance > radius:
                flash(f"That restaurant is outside your {radius:.0f} km delivery radius.", "warning")
                return redirect(url_for("delivery.assignments"))
        ok, message = assign_order(order, user, actor=user.name)
        if not ok:
            flash(message, "danger")
            return redirect(url_for("delivery.assignments"))
    else:
        message = "Assignment already accepted."

    if order.status == STATUS_CONFIRMED:
        order.set_status(STATUS_PREPARED)
        notify(
            order.customer_id,
            "Delivery partner accepted",
            f"{user.name} accepted {order.order_number} and is heading to the restaurant.",
            "order",
            url_for("customer.order_detail", order_id=order.id),
        )
    db.session.commit()
    flash(message or "Assignment accepted.", "success")
    return redirect(url_for("delivery.order_detail", order_id=order.id))


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = _assigned_order(order_id)
    return render_template(
        "delivery/order_detail.html",
        order=order,
        profile=_profile(),
        route=routing.route_for_order(order, _profile()),
        tracking=tracking_payload(order),
    )


@bp.post("/orders/<int:order_id>/status")
@login_required
def update_status(order_id):
    order = _assigned_order(order_id)
    new_status = request.form.get("status", "")
    allowed = {STATUS_PREPARED, STATUS_DISPATCHED, STATUS_DELIVERED}
    if new_status not in allowed:
        flash("Invalid status update.", "danger")
        return redirect(url_for("delivery.order_detail", order_id=order.id))
    if not order.can_transition_to(new_status):
        flash(f"Order cannot move from '{order.status_label}' to that status.", "warning")
        return redirect(url_for("delivery.order_detail", order_id=order.id))
    order.set_status(new_status)
    notify_order_status(order)
    db.session.commit()
    flash(f"Order marked as {order.status_label}.", "success")
    return redirect(url_for("delivery.order_detail", order_id=order.id))


# ---------------------------------------------------------------------------
# live location
# ---------------------------------------------------------------------------
@bp.post("/orders/<int:order_id>/location")
@login_required
def update_location(order_id):
    order = _assigned_order(order_id)
    payload = request.get_json(silent=True) or request.form
    lat = payload.get("latitude") or payload.get("lat")
    lng = payload.get("longitude") or payload.get("lng")
    if not (is_lat(lat) and is_lng(lng)):
        if request.is_json:
            return jsonify({"ok": False, "error": "Invalid coordinates"}), 400
        flash("Enter a valid latitude and longitude.", "danger")
        return redirect(url_for("delivery.order_detail", order_id=order.id))
    record_location(
        _user().id,
        lat,
        lng,
        order_id=order.id,
        speed_kmph=payload.get("speed"),
        source="browser" if request.is_json else "manual",
    )
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True, "message": "Location updated", "lat": float(lat), "lng": float(lng)})
    flash("Live location updated.", "success")
    return redirect(url_for("delivery.order_detail", order_id=order.id))


@bp.post("/availability")
@login_required
def availability():
    profile = _profile()
    value = request.form.get("available")
    if value is None:
        profile.is_available = not profile.is_available
    else:
        profile.is_available = value.lower() in {"1", "true", "yes", "on"}
    db.session.commit()
    flash(
        "You are now available for deliveries."
        if profile.is_available
        else "You are now marked unavailable.",
        "info",
    )
    return redirect(request.referrer or url_for("delivery.dashboard"))


# ---------------------------------------------------------------------------
# route, history, profile
# ---------------------------------------------------------------------------
@bp.get("/route")
@login_required
def route():
    user = _user()
    profile = _profile()
    active = partner_active_orders(user)
    optimized = routing.optimize_batch(active, profile) if active else {
        "stops": [],
        "distance_km": 0,
        "eta_minutes": 0,
        "skipped_orders": [],
    }
    return render_template(
        "delivery/route.html",
        profile=profile,
        orders=active,
        route=optimized,
    )


@bp.get("/history")
@login_required
def history():
    page = max(1, request.args.get("page", 1, type=int))
    pagination = (
        Order.query.filter(
            Order.delivery_partner_id == _user().id,
            Order.status.in_((STATUS_DELIVERED, "cancelled")),
        )
        .order_by(Order.placed_at.desc())
        .paginate(page=page, per_page=12, error_out=False)
    )
    return render_template(
        "delivery/history.html",
        orders=pagination.items,
        pagination=pagination,
        stats=analytics.partner_stats(_user()),
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = _user()
    partner = _profile()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        errors = []
        if len(name) < 3:
            errors.append("Please enter your full name.")
        if phone and not validate_phone(phone):
            errors.append("Please enter a valid phone number.")
        lat_raw = (request.form.get("latitude") or "").strip()
        lng_raw = (request.form.get("longitude") or "").strip()
        if lat_raw or lng_raw:
            if not (is_lat(lat_raw) and is_lng(lng_raw)):
                errors.append("The map location is invalid.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            user.name = name
            user.phone = phone
            partner.vehicle_type = (request.form.get("vehicle_type") or "Bike").strip()[:40]
            partner.vehicle_number = (request.form.get("vehicle_number") or "").strip()[:30].upper()
            if lat_raw and lng_raw:
                partner.current_lat = float(lat_raw)
                partner.current_lng = float(lng_raw)
                partner.last_location_at = utcnow()
            db.session.commit()
            flash("Partner profile updated.", "success")
            return redirect(url_for("delivery.profile"))
    return render_template("delivery/profile.html", partner=partner)
