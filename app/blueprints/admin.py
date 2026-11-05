"""Administrator control panel: users, restaurants, orders, partners,
analytics, settings and reports."""
from __future__ import annotations

import io
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from ..auth import get_current_user, login_required
from ..extensions import db
from ..models import (
    ACTIVE_STATUSES,
    AuditLog,
    ORDER_STATUSES,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_DELIVERY,
    ROLES,
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_DELIVERED,
    STATUS_DISPATCHED,
    STATUS_PLACED,
    STATUS_PREPARED,
    DeliveryPartnerProfile,
    Feedback,
    MenuItem,
    Order,
    Restaurant,
    SystemSetting,
    User,
)
from ..services import analytics, audit, data_pipeline, routing
from ..services.assignment import (
    assign_order,
    auto_assign_order,
    open_assignments_for,
    ranked_partners,
    unassign_order,
)
from ..services.ml_bridge import ml_available
from ..services.notifications import notify, notify_admins, notify_order_status
from ..services.settings import DEFAULT_SETTINGS, all_settings, set_setting
from ..services.tracking import mongo_enabled, tracking_payload
from ..utils import (
    as_decimal,
    is_lat,
    is_lng,
    to_float,
    to_int,
    utcnow,
    validate_email,
    validate_phone,
)

bp = Blueprint("admin", __name__)


def _user() -> User:
    return get_current_user()


@bp.before_request
def _guard():
    user = _user()
    if user is None:
        return None
    if user.role != ROLE_ADMIN:
        abort(403)
    return None


def _parse_time(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@bp.get("/dashboard")
@login_required
def dashboard():
    summary = analytics.summary(30)
    trend = analytics.daily_trend(7)
    today = utcnow().date()
    today_orders = Order.query.filter(Order.placed_at >= datetime.combine(today, datetime.min.time())).count()
    available_partners = (
        DeliveryPartnerProfile.query.join(User)
        .filter(User.is_active.is_(True), DeliveryPartnerProfile.is_available.is_(True))
        .count()
    )
    pending_orders = (
        Order.query.filter(Order.delivery_partner_id.is_(None), Order.status.in_(ACTIVE_STATUSES))
        .order_by(Order.placed_at.asc())
        .limit(6)
        .all()
    )
    recent_orders = Order.query.order_by(Order.placed_at.desc()).limit(8).all()
    partners = analytics.partner_performance(30, limit=4)
    return render_template(
        "admin/dashboard.html",
        summary=summary,
        trend=trend,
        today_orders=today_orders,
        available_partners=available_partners,
        pending_orders=pending_orders,
        recent_orders=recent_orders,
        partners=partners,
    )


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
@bp.get("/users")
@login_required
def users():
    q = (request.args.get("q") or "").strip()
    role = request.args.get("role") or ""
    page = max(1, request.args.get("page", 1, type=int))
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                User.name.ilike(like),
                User.username.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
            )
        )
    if role in ROLES:
        query = query.filter_by(role=role)
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )
    return render_template(
        "admin/users.html",
        users=pagination.items,
        pagination=pagination,
        filters={"q": q, "role": role},
    )


def _user_form_values(user: User | None = None) -> dict:
    return {
        "name": request.form.get("name", user.name if user else ""),
        "username": request.form.get("username", user.username if user else ""),
        "email": request.form.get("email", user.email if user else ""),
        "phone": request.form.get("phone", user.phone or "" if user else ""),
        "role": request.form.get("role", user.role if user else ROLE_CUSTOMER),
        # An unchecked checkbox is absent from POST; do not fall back to the
        # stored value or the box could never be turned off.
        "is_active": (
            request.form.get("is_active", "")
            if request.method == "POST"
            else ("1" if (user.is_active if user else True) else "")
        ),
        "vehicle_type": request.form.get(
            "vehicle_type",
            (user.partner_profile.vehicle_type if user and user.partner_profile else "Bike"),
        ),
        "vehicle_number": request.form.get(
            "vehicle_number",
            (user.partner_profile.vehicle_number or "" if user and user.partner_profile else ""),
        ),
    }


def _validate_user_form(values: dict, editing: User | None) -> list[str]:
    errors = []
    if len(values["name"].strip()) < 3:
        errors.append("Full name must be at least 3 characters.")
    if len(values["username"].strip()) < 3 or " " in values["username"].strip():
        errors.append("Username must be at least 3 characters with no spaces.")
    if not validate_email(values["email"]):
        errors.append("Enter a valid email address.")
    if values["phone"] and not validate_phone(values["phone"]):
        errors.append("Enter a valid phone number.")
    if values["role"] not in ROLES:
        errors.append("Choose a valid role.")
    duplicate_username = User.query.filter(
        db.func.lower(User.username) == values["username"].strip().lower()
    ).first()
    duplicate_email = User.query.filter(
        db.func.lower(User.email) == values["email"].strip().lower()
    ).first()
    if duplicate_username and (editing is None or duplicate_username.id != editing.id):
        errors.append("That username is already taken.")
    if duplicate_email and (editing is None or duplicate_email.id != editing.id):
        errors.append("That email is already registered.")
    return errors


def _apply_user_form(user: User, values: dict, creating: bool) -> None:
    user.name = values["name"].strip()
    user.username = values["username"].strip()
    user.email = values["email"].strip().lower()
    user.phone = values["phone"].strip()
    user.role = values["role"]
    user.is_active = values["is_active"].lower() in {"1", "true", "yes", "on"}
    if values["role"] == ROLE_DELIVERY:
        if user.partner_profile is None:
            user.partner_profile = DeliveryPartnerProfile(
                vehicle_type=values["vehicle_type"] or "Bike",
                vehicle_number=values["vehicle_number"],
            )
        else:
            user.partner_profile.vehicle_type = values["vehicle_type"] or "Bike"
            user.partner_profile.vehicle_number = values["vehicle_number"]
    if creating and values["role"] == ROLE_CUSTOMER and user.customer_profile is None:
        from ..models import CustomerProfile

        user.customer_profile = CustomerProfile()


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
def user_new():
    values = _user_form_values()
    if request.method == "POST":
        password = request.form.get("password") or ""
        errors = _validate_user_form(values, None)
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            user = User()
            _apply_user_form(user, values, creating=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            audit.log_action(_user(), "user_created", user.username, user.role_label, commit=True)
            notify_admins(
                "User account created",
                f"{user.name} ({user.role_label}) was added by {_user().name}.",
                "system",
                url_for("admin.users"),
            )
            db.session.commit()
            flash(f"{user.name} created successfully.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", values=values, editing=None)


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def user_edit(user_id):
    account = db.session.get(User, user_id)
    if account is None:
        abort(404)
    values = _user_form_values(account)
    if request.method == "POST":
        errors = _validate_user_form(values, account)
        if account.id == _user().id and values["role"] != ROLE_ADMIN:
            errors.append("You cannot remove your own administrator role.")
        if account.id == _user().id and values["is_active"].lower() not in {"1", "true", "yes", "on"}:
            errors.append("You cannot deactivate your own account.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            _apply_user_form(account, values, creating=False)
            new_password = request.form.get("password") or ""
            if new_password:
                if len(new_password) < 8:
                    flash("The new password must be at least 8 characters.", "danger")
                    return render_template("admin/user_form.html", values=values, editing=account)
                account.set_password(new_password)
                audit.log_action(_user(), "password_reset", account.username, commit=True)
            db.session.commit()
            audit.log_action(_user(), "user_updated", account.username, account.role_label, commit=True)
            flash(f"{account.name} updated.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", values=values, editing=account)


@bp.post("/users/<int:user_id>/toggle")
@login_required
def user_toggle(user_id):
    account = db.session.get(User, user_id)
    if account is None:
        abort(404)
    if account.id == _user().id:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("admin.users"))
    account.is_active = not account.is_active
    db.session.commit()
    audit.log_action(_user(), "user_toggled", account.username, "active" if account.is_active else "inactive", commit=True)
    flash(
        f"{account.name} is now {'active' if account.is_active else 'inactive'}.",
        "info",
    )
    return redirect(request.referrer or url_for("admin.users"))


# ---------------------------------------------------------------------------
# restaurants & menu
# ---------------------------------------------------------------------------
@bp.get("/restaurants")
@login_required
def restaurants():
    q = (request.args.get("q") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    query = Restaurant.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Restaurant.name.ilike(like),
                Restaurant.cuisine.ilike(like),
                Restaurant.city.ilike(like),
            )
        )
    pagination = query.order_by(Restaurant.name.asc()).paginate(
        page=page, per_page=12, error_out=False
    )
    stats = {r.id: analytics.restaurant_stats(r, 30) for r in pagination.items}
    return render_template(
        "admin/restaurants.html",
        restaurants=pagination.items,
        pagination=pagination,
        stats=stats,
        q=q,
    )


def _restaurant_values(restaurant: Restaurant | None = None) -> dict:
    def current(field: str, default=""):
        if request.method == "POST":
            return request.form.get(field, default)
        if restaurant is None:
            return default
        value = getattr(restaurant, field, default)
        if field in {"opening_time", "closing_time"} and value:
            return value.strftime("%H:%M")
        return value if value is not None else default

    return {
        "name": current("name"),
        "description": current("description"),
        "cuisine": current("cuisine"),
        "address": current("address"),
        "city": current("city"),
        "phone": current("phone"),
        "email": current("email"),
        "latitude": current("latitude"),
        "longitude": current("longitude"),
        "opening_time": current("opening_time"),
        "closing_time": current("closing_time"),
        "image_url": current("image_url"),
        "is_active": (
            request.form.get("is_active", "")
            if request.method == "POST"
            else ("1" if (restaurant.is_active if restaurant else True) else "")
        ),
    }


def _validate_restaurant(values: dict) -> list[str]:
    errors = []
    if len(values["name"].strip()) < 2:
        errors.append("Restaurant name is required.")
    if not values["cuisine"].strip():
        errors.append("Cuisine is required.")
    if values["email"] and not validate_email(values["email"]):
        errors.append("Enter a valid restaurant email.")
    if values["phone"] and not validate_phone(values["phone"]):
        errors.append("Enter a valid restaurant phone.")
    lat, lng = values["latitude"], values["longitude"]
    if (lat or lng) and not (is_lat(lat) and is_lng(lng)):
        errors.append("Restaurant coordinates are invalid.")
    if (values["opening_time"] and not values["closing_time"]) or (
        values["closing_time"] and not values["opening_time"]
    ):
        errors.append("Set both opening and closing time, or leave both blank.")
    if values["opening_time"] and _parse_time(values["opening_time"]) is None:
        errors.append("Opening time must be in HH:MM format.")
    if values["closing_time"] and _parse_time(values["closing_time"]) is None:
        errors.append("Closing time must be in HH:MM format.")
    return errors


def _apply_restaurant(restaurant: Restaurant, values: dict) -> None:
    restaurant.name = values["name"].strip()
    restaurant.description = values["description"].strip()
    restaurant.cuisine = values["cuisine"].strip()
    restaurant.address = values["address"].strip()
    restaurant.city = values["city"].strip()
    restaurant.phone = values["phone"].strip()
    restaurant.email = values["email"].strip()
    restaurant.latitude = float(values["latitude"]) if values["latitude"] else None
    restaurant.longitude = float(values["longitude"]) if values["longitude"] else None
    restaurant.opening_time = _parse_time(values["opening_time"])
    restaurant.closing_time = _parse_time(values["closing_time"])
    restaurant.image_url = values["image_url"].strip()
    restaurant.is_active = values["is_active"].lower() in {"1", "true", "yes", "on"}


@bp.route("/restaurants/new", methods=["GET", "POST"])
@login_required
def restaurant_new():
    values = _restaurant_values()
    if request.method == "POST":
        errors = _validate_restaurant(values)
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            restaurant = Restaurant()
            _apply_restaurant(restaurant, values)
            db.session.add(restaurant)
            db.session.commit()
            audit.log_action(_user(), "restaurant_created", restaurant.name, "", commit=True)
            flash(f"{restaurant.name} added.", "success")
            return redirect(url_for("admin.restaurants"))
    return render_template("admin/restaurant_form.html", values=values, editing=None)


@bp.route("/restaurants/<int:restaurant_id>/edit", methods=["GET", "POST"])
@login_required
def restaurant_edit(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    values = _restaurant_values(restaurant)
    if request.method == "POST":
        errors = _validate_restaurant(values)
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            _apply_restaurant(restaurant, values)
            db.session.commit()
            audit.log_action(_user(), "restaurant_updated", restaurant.name, "", commit=True)
            flash(f"{restaurant.name} updated.", "success")
            return redirect(url_for("admin.restaurants"))
    return render_template("admin/restaurant_form.html", values=values, editing=restaurant)


@bp.post("/restaurants/<int:restaurant_id>/toggle")
@login_required
def restaurant_toggle(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    restaurant.is_active = not restaurant.is_active
    db.session.commit()
    audit.log_action(_user(), "restaurant_toggled", restaurant.name, "active" if restaurant.is_active else "inactive", commit=True)
    flash(
        f"{restaurant.name} is now {'active' if restaurant.is_active else 'inactive'}.",
        "info",
    )
    return redirect(request.referrer or url_for("admin.restaurants"))


@bp.post("/restaurants/<int:restaurant_id>/delete")
@login_required
def restaurant_delete(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    if restaurant.orders.count() or restaurant.feedbacks.count():
        restaurant.is_active = False
        db.session.commit()
        flash(
            f"{restaurant.name} has order history, so it was deactivated instead of deleted.",
            "warning",
        )
    else:
        name = restaurant.name
        db.session.delete(restaurant)
        db.session.commit()
        audit.log_action(_user(), "restaurant_deleted", name, "", commit=True)
        flash(f"{name} deleted.", "info")
    return redirect(url_for("admin.restaurants"))


@bp.get("/restaurants/<int:restaurant_id>/menu")
@login_required
def menu(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    items = (
        MenuItem.query.filter_by(restaurant_id=restaurant.id)
        .order_by(MenuItem.category.asc(), MenuItem.name.asc())
        .all()
    )
    return render_template("admin/menu.html", restaurant=restaurant, items=items)


def _menu_values(item: MenuItem | None = None) -> dict:
    def value(field, default=""):
        if request.method == "POST":
            return request.form.get(field, default)
        return getattr(item, field, default) if item is not None else default

    return {
        "name": value("name"),
        "description": value("description"),
        "category": value("category", "Main Course"),
        "price": value("price"),
        "prep_time_min": value("prep_time_min", 20),
        "is_veg": (
            request.form.get("is_veg", "")
            if request.method == "POST"
            else ("1" if (item.is_veg if item else True) else "")
        ),
        "is_available": (
            request.form.get("is_available", "")
            if request.method == "POST"
            else ("1" if (item.is_available if item else True) else "")
        ),
        "image_url": value("image_url"),
    }


@bp.route("/restaurants/<int:restaurant_id>/menu/new", methods=["GET", "POST"])
@login_required
def menu_item_new(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    values = _menu_values()
    if request.method == "POST":
        errors = []
        if len(values["name"].strip()) < 2:
            errors.append("Item name is required.")
        if to_float(values["price"], -1) < 0:
            errors.append("Price must be zero or more.")
        if not 1 <= to_int(values["prep_time_min"], 20) <= 180:
            errors.append("Preparation time must be between 1 and 180 minutes.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            item = MenuItem(restaurant_id=restaurant.id)
            _apply_menu_item(item, values)
            db.session.add(item)
            db.session.commit()
            audit.log_action(_user(), "menu_item_added", f"{restaurant.name} - {item.name}", "", commit=True)
            flash(f"{item.name} added to the menu.", "success")
            return redirect(url_for("admin.menu", restaurant_id=restaurant.id))
    return render_template(
        "admin/menu_item_form.html", restaurant=restaurant, values=values, editing=None
    )


@bp.route("/menu/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def menu_item_edit(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None:
        abort(404)
    values = _menu_values(item)
    if request.method == "POST":
        errors = []
        if len(values["name"].strip()) < 2:
            errors.append("Item name is required.")
        if to_float(values["price"], -1) < 0:
            errors.append("Price must be zero or more.")
        if not 1 <= to_int(values["prep_time_min"], 20) <= 180:
            errors.append("Preparation time must be between 1 and 180 minutes.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            _apply_menu_item(item, values)
            db.session.commit()
            audit.log_action(_user(), "menu_item_updated", f"{item.restaurant.name} - {item.name}", "", commit=True)
            flash(f"{item.name} updated.", "success")
            return redirect(url_for("admin.menu", restaurant_id=item.restaurant_id))
    return render_template(
        "admin/menu_item_form.html",
        restaurant=item.restaurant,
        values=values,
        editing=item,
    )


def _apply_menu_item(item: MenuItem, values: dict) -> None:
    item.name = values["name"].strip()
    item.description = values["description"].strip()
    item.category = values["category"].strip() or "Main Course"
    item.price = as_decimal(values["price"])
    item.prep_time_min = to_int(values["prep_time_min"], 20)
    item.is_veg = values["is_veg"].lower() in {"1", "true", "yes", "on"}
    item.is_available = values["is_available"].lower() in {"1", "true", "yes", "on"}
    item.image_url = values["image_url"].strip()


@bp.post("/menu/<int:item_id>/toggle")
@login_required
def menu_item_toggle(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None:
        abort(404)
    item.is_available = not item.is_available
    db.session.commit()
    audit.log_action(_user(), "menu_item_toggled", item.name, "available" if item.is_available else "unavailable", commit=True)
    flash(f"{item.name} is now {'available' if item.is_available else 'unavailable'}.", "info")
    return redirect(url_for("admin.menu", restaurant_id=item.restaurant_id))


@bp.post("/menu/<int:item_id>/delete")
@login_required
def menu_item_delete(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None:
        abort(404)
    restaurant_id = item.restaurant_id
    name = item.name
    db.session.delete(item)
    db.session.commit()
    audit.log_action(_user(), "menu_item_deleted", name, "", commit=True)
    flash(f"{name} removed from the menu.", "info")
    return redirect(url_for("admin.menu", restaurant_id=restaurant_id))


# ---------------------------------------------------------------------------
# orders & assignment
# ---------------------------------------------------------------------------
@bp.get("/orders")
@login_required
def orders():
    status = request.args.get("status", "")
    q = (request.args.get("q") or "").strip()
    assignment = request.args.get("assignment", "")
    page = max(1, request.args.get("page", 1, type=int))
    query = Order.query
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    if assignment == "unassigned":
        query = query.filter(Order.delivery_partner_id.is_(None))
    elif assignment == "assigned":
        query = query.filter(Order.delivery_partner_id.isnot(None))
    if q:
        like = f"%{q}%"
        query = (
            query.join(User, Order.customer_id == User.id)
            .join(Restaurant, Order.restaurant_id == Restaurant.id)
            .filter(
                db.or_(
                    Order.order_number.ilike(like),
                    User.name.ilike(like),
                    Restaurant.name.ilike(like),
                )
            )
        )
    pagination = query.order_by(Order.placed_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )
    return render_template(
        "admin/orders.html",
        orders=pagination.items,
        pagination=pagination,
        filters={"status": status, "q": q, "assignment": assignment},
        statuses=ORDER_STATUSES,
    )


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    return render_template(
        "admin/order_detail.html",
        order=order,
        ranked=ranked_partners(order),
        tracking=tracking_payload(order),
        route=routing.route_for_order(
            order, order.delivery_partner.partner_profile if order.delivery_partner else None
        ),
    )


@bp.post("/orders/<int:order_id>/assign")
@login_required
def order_assign(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    partner_id = to_int(request.form.get("partner_id"), 0)
    partner = db.session.get(User, partner_id) if partner_id else None
    if partner is None:
        flash("Choose a delivery partner.", "danger")
    else:
        ok, message = assign_order(order, partner, actor=_user().name, force=True)
        if ok:
            db.session.commit()
            audit.log_action(_user(), "order_assigned", order.order_number, partner.name, commit=True)
            flash(message, "success")
        else:
            flash(message, "danger")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/auto-assign")
@login_required
def order_auto_assign(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    partner = auto_assign_order(order, actor=_user().name, force=True)
    if partner:
        db.session.commit()
        audit.log_action(_user(), "order_auto_assigned", order.order_number, partner.name, commit=True)
        flash(f"Auto-assigned to {partner.name}.", "success")
    else:
        db.session.commit()
        flash("No eligible partner was found. Assign manually.", "warning")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/unassign")
@login_required
def order_unassign(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    unassign_order(order, actor=_user().name)
    db.session.commit()
    audit.log_action(_user(), "order_unassigned", order.order_number, "", commit=True)
    flash("Order is now unassigned.", "info")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/status")
@login_required
def order_status(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    new_status = request.form.get("status", "")
    if new_status not in ORDER_STATUSES:
        flash("Invalid status.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    if not order.can_transition_to(new_status):
        flash(f"Cannot move from {order.status_label} to that status.", "warning")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    order.set_status(new_status)
    if new_status == STATUS_CANCELLED:
        order.cancellation_reason = (request.form.get("reason") or "Cancelled by admin")[:255]
    notify_order_status(order)
    if new_status == STATUS_CANCELLED and order.delivery_partner_id:
        notify(
            order.delivery_partner_id,
            "Order cancelled",
            f"{order.order_number} was cancelled by the administrator.",
            "assignment",
            url_for("delivery.dashboard"),
        )
    db.session.commit()
    audit.log_action(_user(), "order_status_changed", order.order_number, new_status, commit=True)
    flash(f"Order marked as {order.status_label}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


# ---------------------------------------------------------------------------
# partners
# ---------------------------------------------------------------------------
@bp.get("/partners")
@login_required
def partners():
    performance = analytics.partner_performance(30)
    unassigned = (
        Order.query.filter(Order.delivery_partner_id.is_(None), Order.status.in_(ACTIVE_STATUSES))
        .order_by(Order.placed_at.asc())
        .all()
    )
    return render_template(
        "admin/partners.html",
        partners=performance,
        unassigned=unassigned,
    )


@bp.post("/partners/<int:user_id>/availability")
@login_required
def partner_availability(user_id):
    profile = DeliveryPartnerProfile.query.filter_by(user_id=user_id).first()
    if profile is None:
        abort(404)
    profile.is_available = not profile.is_available
    db.session.commit()
    audit.log_action(_user(), "partner_availability", profile.user.name, "available" if profile.is_available else "off duty", commit=True)
    flash(
        f"{profile.user.name} is now {'available' if profile.is_available else 'unavailable'}.",
        "info",
    )
    return redirect(url_for("admin.partners"))


# ---------------------------------------------------------------------------
# analytics, feedback, settings, reports
# ---------------------------------------------------------------------------
@bp.get("/analytics")
@login_required
def analytics_page():
    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90) else 30
    bundle = analytics.analytics_bundle(days)
    return render_template("admin/analytics.html", bundle=bundle, days=days)


@bp.get("/feedback")
@login_required
def feedback():
    page = max(1, request.args.get("page", 1, type=int))
    rating = request.args.get("rating", type=int)
    query = Feedback.query
    if rating and 1 <= rating <= 5:
        query = query.filter(Feedback.restaurant_rating == rating)
    pagination = query.order_by(Feedback.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )
    rating_counts = dict(
        db.session.query(Feedback.restaurant_rating, db.func.count(Feedback.id))
        .group_by(Feedback.restaurant_rating)
        .all()
    )
    total = sum(rating_counts.values())
    positive = rating_counts.get(4, 0) + rating_counts.get(5, 0)
    stats = {
        "total": total,
        "rating_counts": rating_counts,
        "avg_restaurant": db.session.query(db.func.avg(Feedback.restaurant_rating)).scalar() or 0.0,
        "avg_partner": db.session.query(db.func.avg(Feedback.partner_rating))
        .filter(Feedback.partner_rating.isnot(None))
        .scalar()
        or 0.0,
        "partner_reviews": db.session.query(db.func.count(Feedback.partner_rating))
        .filter(Feedback.partner_rating.isnot(None))
        .scalar()
        or 0,
        "positive_percent": round(positive / total * 100, 1) if total else 0.0,
    }
    return render_template(
        "admin/feedback.html",
        feedback=pagination.items,
        pagination=pagination,
        rating=rating,
        stats=stats,
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        if request.form.get("action") == "reset":
            for key, (value, _description) in DEFAULT_SETTINGS.items():
                set_setting(key, value)
            db.session.commit()
            flash("All optimization settings were restored to their defaults.", "info")
            return redirect(url_for("admin.settings"))

        errors = []
        numeric_rules = {
            "base_delivery_fee": (0, 500, "Base delivery fee"),
            "per_km_fee": (0, 200, "Per km fee"),
            "avg_speed_kmph": (5, 100, "Average speed"),
            "traffic_factor": (1, 3, "Traffic factor"),
            "max_delivery_radius_km": (1, 100, "Maximum radius"),
            "max_orders_per_partner": (1, 10, "Max orders per partner"),
            "prep_buffer_min": (0, 60, "Preparation buffer"),
            "partner_commission_percent": (0, 100, "Partner commission"),
        }
        for key, (low, high, label) in numeric_rules.items():
            raw = request.form.get(key, "").strip()
            try:
                value = float(raw)
                if not low <= value <= high:
                    errors.append(f"{label} must be between {low} and {high}.")
            except ValueError:
                errors.append(f"{label} must be a number.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            for key in numeric_rules:
                set_setting(key, request.form.get(key).strip())
            set_setting(
                "auto_assign_orders",
                "true" if request.form.get("auto_assign_orders") else "false",
            )
            db.session.commit()
            audit.log_action(_user(), "settings_updated", "optimization", ", ".join(numeric_rules), commit=True)
            flash("Optimization settings saved.", "success")
            return redirect(url_for("admin.settings"))

    values = all_settings()
    return render_template(
        "admin/settings.html",
        values=values,
        defaults=DEFAULT_SETTINGS,
        ml_ready=ml_available(),
        mongo_ready=mongo_enabled(),
    )


@bp.get("/reports/orders.csv")
@login_required
def report_orders():
    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90) else 30
    data = analytics.orders_csv(days)
    return send_file(
        io.BytesIO(data.encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"orders_report_{days}d.csv",
    )


@bp.get("/reports/partners.csv")
@login_required
def report_partners():
    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90) else 30
    data = analytics.partners_csv(days)
    return send_file(
        io.BytesIO(data.encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"partners_report_{days}d.csv",
    )


# ---------------------------------------------------------------------------
# audit trail (SRS 3.13)
# ---------------------------------------------------------------------------
@bp.get("/audit")
@login_required
def audit_page():
    action = (request.args.get("action") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    query = AuditLog.query
    if action:
        query = query.filter_by(action=action)
    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    actions = [a for (a,) in db.session.query(AuditLog.action).distinct().all()]
    actions = sorted(a for a in actions if a)
    return render_template(
        "admin/audit.html",
        logs=pagination.items,
        pagination=pagination,
        action=action,
        actions=actions,
    )


# ---------------------------------------------------------------------------
# data pipeline (SRS 3.10 / 3.11)
# ---------------------------------------------------------------------------
@bp.get("/data")
@login_required
def data_page():
    sources = data_pipeline.source_files()
    sql = data_pipeline.sql_status()
    from ..extensions import _get_session

    sql["engine"] = "SQL Server (T-SQL)" if _get_session().connection.kind == "mssql" else "SQLite (fallback)"
    mongo = data_pipeline.mongo_status()
    report = data_pipeline.run_validation()
    return render_template(
        "admin/data.html",
        sources=sources,
        sql=sql,
        mongo=mongo,
        report=report,
    )


@bp.post("/data/run")
@login_required
def data_run():
    report = data_pipeline.run_validation()
    flagged = sum(len(v) for v in report["issues"].values())
    audit.log_action(_user(), "data_validation", "ingested_rows", f"{flagged} issues flagged")
    db.session.commit()
    if flagged:
        flash(
            f"Data validation finished - {flagged} issue(s) flagged. See the report below.",
            "warning",
        )
    else:
        flash("Data validation finished - all ingested rows passed the checks.", "success")
    return redirect(url_for("admin.data_page"))


# ---------------------------------------------------------------------------
# route optimizer (SRS 3.7) - admin tooling
# ---------------------------------------------------------------------------
@bp.get("/optimizer")
@login_required
def optimizer_page():
    """Pick a set of orders and a partner; compute the optimized route."""
    status = request.args.get("status", "")
    q = (request.args.get("q") or "").strip()
    query = Order.query.filter(Order.status.in_(ACTIVE_STATUSES)).order_by(Order.placed_at.asc())
    if status == "unassigned":
        query = query.filter(Order.delivery_partner_id.is_(None))
    elif status == "assigned":
        query = query.filter(Order.delivery_partner_id.isnot(None))
    if q:
        like = f"%{q}%"
        query = (
            query.join(User, Order.customer_id == User.id)
            .join(Restaurant, Order.restaurant_id == Restaurant.id)
            .filter(db.or_(Order.order_number.ilike(like), User.name.ilike(like), Restaurant.name.ilike(like)))
        )
    orders = query.limit(30).all()
    partners = (
        User.query.join(DeliveryPartnerProfile, User.id == DeliveryPartnerProfile.user_id)
        .filter(User.is_active.is_(True), User.role == ROLE_DELIVERY)
        .order_by(User.name.asc())
        .all()
    )
    selected = request.args.getlist("orders")
    selected_ids = [to_int(v, 0) for v in selected if to_int(v, 0)]
    selected_ids = [i for i in selected_ids if i]
    partner_id = to_int(request.args.get("partner_id"), 0)

    route = None
    if selected_ids:
        picked = [order for order in orders if order.id in selected_ids]
        if not picked:
            picked = [db.session.get(Order, i) for i in selected_ids]
            picked = [o for o in picked if o is not None]
        profile = (
            DeliveryPartnerProfile.query.filter_by(user_id=partner_id).first()
            if partner_id else None
        )
        route = routing.optimize_batch(picked, profile)
        route["order_numbers"] = [o.order_number for o in picked]
    return render_template(
        "admin/optimizer.html",
        orders=orders,
        partners=partners,
        route=route,
        selected_ids=selected_ids,
        partner_id=partner_id,
        status=status,
        q=q,
    )
