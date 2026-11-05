"""Customer area: profile, cart, checkout, orders, tracking, feedback."""
from __future__ import annotations

from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..auth import get_current_user, login_required, role_required
from ..extensions import db
from ..models import (
    ACTIVE_STATUSES,
    ROLE_CUSTOMER,
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_DELIVERED,
    CustomerProfile,
    Feedback,
    MenuItem,
    Order,
    OrderItem,
    Restaurant,
)
from ..services import analytics, routing
from ..services.assignment import auto_assign_order
from ..services.cart import (
    add_item,
    clear_cart,
    get_cart,
    remove_item,
    update_item,
)
from ..services.notifications import notify, notify_admins, notify_order_status
from ..services.settings import get_float
from ..services.tracking import tracking_payload
from ..utils import (
    as_decimal,
    generate_order_number,
    haversine_km,
    is_lat,
    is_lng,
    format_money,
    safe_next_url,
    to_int,
    utcnow,
    validate_email,
    validate_phone,
)

bp = Blueprint("customer", __name__)


def _user():
    return get_current_user()


@bp.before_request
def _guard():
    if _user() is None:
        return None
    if _user().role != ROLE_CUSTOMER:
        abort(403)
    return None


def _own_order(order_id: int) -> Order:
    order = Order.query.filter_by(id=order_id, customer_id=_user().id).first()
    if order is None:
        abort(404)
    return order


def _delivery_fee(restaurant: Restaurant, profile: CustomerProfile) -> tuple[Decimal, float]:
    distance = 0.0
    if restaurant.has_location and profile.has_location:
        distance = haversine_km(
            restaurant.latitude,
            restaurant.longitude,
            profile.latitude,
            profile.longitude,
        )
    fee = as_decimal(get_float("base_delivery_fee", 25)) + as_decimal(
        get_float("per_km_fee", 8)
    ) * as_decimal(distance)
    return fee, round(distance, 2)


@bp.get("/dashboard")
@login_required
def dashboard():
    user = _user()
    stats = analytics.customer_stats(user)
    active_orders = (
        Order.query.filter(
            Order.customer_id == user.id,
            Order.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Order.placed_at.desc())
        .all()
    )
    recent_orders = (
        Order.query.filter_by(customer_id=user.id)
        .order_by(Order.placed_at.desc())
        .limit(5)
        .all()
    )
    profile = user.customer_profile
    recommended_query = Restaurant.query.filter_by(is_active=True)
    if profile and profile.city:
        # NOTE: build the OR conditionally - a bare False literal inside
        # db.or_ renders invalid SQL on SQL Server (error 4145) and 500s
        # the dashboard for freshly registered users with no preferences.
        city_match = Restaurant.city == profile.city
        if profile.preference_list:
            recommended_query = recommended_query.filter(
                db.or_(
                    city_match,
                    Restaurant.cuisine.in_(profile.preference_list),
                )
            )
        else:
            recommended_query = recommended_query.filter(city_match)
    recommended = recommended_query.order_by(Restaurant.rating_avg.desc()).limit(3).all()
    if not recommended:
        recommended = (
            Restaurant.query.filter_by(is_active=True)
            .order_by(Restaurant.rating_avg.desc())
            .limit(3)
            .all()
        )
    return render_template(
        "customer/dashboard.html",
        stats=stats,
        active_orders=active_orders,
        recent_orders=recent_orders,
        recommended=recommended,
    )


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = _user()
    profile = user.customer_profile
    if profile is None:
        profile = CustomerProfile(user_id=user.id)
        db.session.add(profile)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        phone = (request.form.get("phone") or "").strip()
        errors = []
        if len(name) < 3:
            errors.append("Please enter your full name.")
        if not validate_email(email):
            errors.append("Please enter a valid email address.")
        if phone and not validate_phone(phone):
            errors.append("Please enter a valid phone number.")
        from ..models import User as UserModel

        if UserModel.query.filter(
            UserModel.email == email, UserModel.id != user.id
        ).first():
            errors.append("That email address is already registered.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            user.name = name
            user.email = email
            user.phone = phone
            profile.address = (request.form.get("address") or "").strip()
            profile.city = (request.form.get("city") or "").strip()
            profile.state = (request.form.get("state") or "").strip()
            profile.pincode = (request.form.get("pincode") or "").strip()
            profile.food_preferences = (request.form.get("food_preferences") or "").strip()[:500]
            lat = request.form.get("latitude") or ""
            lng = request.form.get("longitude") or ""
            if lat and lng:
                if not (is_lat(lat) and is_lng(lng)):
                    flash("Please provide a valid latitude and longitude.", "danger")
                    return render_template("customer/profile.html", profile=profile)
                profile.latitude = float(lat)
                profile.longitude = float(lng)
            else:
                profile.latitude = None
                profile.longitude = None
            favorite = request.form.get("favorite_restaurant_id")
            profile.favorite_restaurant_id = to_int(favorite, 0) or None
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("customer.profile"))

    restaurants = Restaurant.query.filter_by(is_active=True).order_by(Restaurant.name).all()
    return render_template(
        "customer/profile.html", profile=profile, restaurants=restaurants
    )


# ---------------------------------------------------------------------------
# cart
# ---------------------------------------------------------------------------
@bp.get("/cart")
@login_required
def cart():
    data = get_cart()
    fee = Decimal("0.00")
    distance = 0.0
    if data["restaurant"]:
        fee, distance = _delivery_fee(data["restaurant"], _user().customer_profile or CustomerProfile())
    return render_template(
        "customer/cart.html",
        cart=data,
        delivery_fee=fee,
        distance=distance,
        total=data["subtotal"] + fee,
    )


@bp.post("/cart/add/<int:item_id>")
@login_required
def cart_add(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None or not item.is_available or not item.restaurant.is_active:
        flash("That item is currently unavailable.", "danger")
        return redirect(request.form.get("next") or url_for("main.restaurants"))
    current = get_cart()
    if current["restaurant"] and current["restaurant"].id != item.restaurant_id:
        clear_cart()
        flash(
            f"Your cart was cleared because it contained items from "
            f"{current['restaurant'].name}. You can only order from one restaurant at a time.",
            "info",
        )
    add_item(item.id, max(1, min(20, to_int(request.form.get("quantity"), 1))))
    flash(f"{item.name} added to cart.", "success")
    target = safe_next_url(request.form.get("next"))
    return redirect(target or url_for("main.restaurant_detail", restaurant_id=item.restaurant_id))


@bp.post("/cart/update/<int:item_id>")
@login_required
def cart_update(item_id):
    update_item(item_id, to_int(request.form.get("quantity"), 1))
    return redirect(url_for("customer.cart"))


@bp.post("/cart/remove/<int:item_id>")
@login_required
def cart_remove(item_id):
    remove_item(item_id)
    flash("Item removed from cart.", "info")
    return redirect(url_for("customer.cart"))


@bp.post("/cart/clear")
@login_required
def cart_clear():
    clear_cart()
    flash("Cart cleared.", "info")
    return redirect(url_for("customer.cart"))


# ---------------------------------------------------------------------------
# checkout
# ---------------------------------------------------------------------------
@bp.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    user = _user()
    data = get_cart()
    if not data["items"] or data["restaurant"] is None:
        flash("Your cart is empty. Add some food first.", "info")
        return redirect(url_for("main.restaurants"))

    restaurant = data["restaurant"]
    profile = user.customer_profile or CustomerProfile(user_id=user.id)
    fee = Decimal("0.00")
    distance = 0.0

    if request.method == "POST":
        address = (request.form.get("delivery_address") or "").strip()
        lat_raw = (request.form.get("latitude") or "").strip()
        lng_raw = (request.form.get("longitude") or "").strip()
        payment_method = request.form.get("payment_method", "COD")
        notes = (request.form.get("notes") or "").strip()[:500]
        errors = []
        if len(address) < 8:
            errors.append("Please enter a complete delivery address.")
        if payment_method not in {"COD", "Easypaisa", "Card"}:
            errors.append("Choose a valid payment method.")
        latitude = longitude = None
        if lat_raw or lng_raw:
            if not (is_lat(lat_raw) and is_lng(lng_raw)):
                errors.append("The map location is invalid. Pick it again.")
            else:
                latitude, longitude = float(lat_raw), float(lng_raw)

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            # distance & fee (use submitted coords, otherwise saved profile coords)
            fee_distance = 0.0
            if restaurant.has_location:
                if latitude is not None and longitude is not None:
                    fee_distance = haversine_km(
                        restaurant.latitude, restaurant.longitude, latitude, longitude
                    )
                elif profile.has_location:
                    fee_distance = haversine_km(
                        restaurant.latitude,
                        restaurant.longitude,
                        profile.latitude,
                        profile.longitude,
                    )
            fee = as_decimal(get_float("base_delivery_fee", 25)) + as_decimal(
                get_float("per_km_fee", 8)
            ) * as_decimal(fee_distance)

            order = Order(
                order_number=_unique_order_number(),
                customer_id=user.id,
                restaurant_id=restaurant.id,
                status=STATUS_CONFIRMED,
                confirmed_at=utcnow(),
                placed_at=utcnow(),
                payment_method=payment_method,
                payment_status="Pending" if payment_method == "COD" else "Paid",
                subtotal=data["subtotal"],
                delivery_fee=fee,
                total=data["subtotal"] + fee,
                delivery_address=address,
                delivery_lat=latitude if latitude is not None else (profile.latitude if profile.has_location else None),
                delivery_lng=longitude if longitude is not None else (profile.longitude if profile.has_location else None),
                distance_km=round(fee_distance, 2),
                notes=notes,
            )
            for entry in data["items"]:
                item = entry["item"]
                qty = entry["quantity"]
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
            db.session.add(order)
            db.session.flush()  # assign order.id

            order.estimated_delivery_min = routing.estimate_eta(order)
            notify(
                user.id,
                "Order confirmed",
                f"{order.order_number} from {restaurant.name} is confirmed. Estimated delivery in "
                f"{order.estimated_delivery_min} min.",
                "order",
                url_for("customer.order_detail", order_id=order.id),
            )
            notify_admins(
                "New order received",
                f"{order.order_number} - {restaurant.name} ({format_money(order.total)}).",
                "order",
                url_for("admin.order_detail", order_id=order.id),
            )
            assigned = auto_assign_order(order)
            db.session.commit()
            clear_cart()
            if assigned:
                flash("Order placed and a delivery partner has been assigned.", "success")
            else:
                flash("Order placed. We are finding a delivery partner.", "success")
            return redirect(url_for("customer.order_detail", order_id=order.id))

    fee, distance = _delivery_fee(restaurant, profile)
    return render_template(
        "customer/checkout.html",
        cart=data,
        restaurant=restaurant,
        profile=profile,
        delivery_fee=fee,
        distance=distance,
        total=data["subtotal"] + fee,
    )


def _unique_order_number() -> str:
    for _ in range(10):
        number = generate_order_number()
        if Order.query.filter_by(order_number=number).first() is None:
            return number
    return generate_order_number() + "X"


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------
@bp.get("/orders")
@login_required
def orders():
    status = request.args.get("status", "")
    page = max(1, request.args.get("page", 1, type=int))
    query = Order.query.filter_by(customer_id=_user().id)
    if status in ACTIVE_STATUSES or status in {"delivered", "cancelled"}:
        query = query.filter_by(status=status)
    pagination = query.order_by(Order.placed_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    return render_template(
        "customer/orders.html",
        orders=pagination.items,
        pagination=pagination,
        active_status=status,
    )


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = _own_order(order_id)
    return render_template(
        "customer/order_detail.html",
        order=order,
        tracking=tracking_payload(order),
    )


@bp.post("/orders/<int:order_id>/cancel")
@login_required
def cancel_order(order_id):
    order = _own_order(order_id)
    if not order.can_cancel:
        flash("This order can no longer be cancelled. Contact support for help.", "warning")
        return redirect(url_for("customer.order_detail", order_id=order.id))
    reason = (request.form.get("reason") or "Cancelled by customer").strip()[:255]
    order.set_status(STATUS_CANCELLED)
    order.cancellation_reason = reason
    notify_order_status(order)
    if order.delivery_partner_id:
        notify(
            order.delivery_partner_id,
            "Order cancelled",
            f"{order.order_number} was cancelled by the customer.",
            "assignment",
            url_for("delivery.dashboard"),
        )
    notify_admins(
        "Order cancelled",
        f"{order.order_number} was cancelled by {order.customer.name}: {reason}",
        "alert",
        url_for("admin.order_detail", order_id=order.id),
    )
    db.session.commit()
    flash("Order cancelled.", "info")
    return redirect(url_for("customer.order_detail", order_id=order.id))


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------
@bp.route("/orders/<int:order_id>/feedback", methods=["GET", "POST"])
@login_required
def feedback(order_id):
    order = _own_order(order_id)
    if order.status != STATUS_DELIVERED:
        flash("You can rate an order only after it is delivered.", "warning")
        return redirect(url_for("customer.order_detail", order_id=order.id))
    if order.feedback is not None:
        flash("You have already rated this order. Thank you!", "info")
        return redirect(url_for("customer.order_detail", order_id=order.id))

    if request.method == "POST":
        try:
            restaurant_rating = int(request.form.get("restaurant_rating", "0"))
            partner_rating_raw = request.form.get("partner_rating", "")
            partner_rating = int(partner_rating_raw) if partner_rating_raw else None
        except ValueError:
            restaurant_rating, partner_rating = 0, None

        errors = []
        if not 1 <= restaurant_rating <= 5:
            errors.append("Please rate the restaurant from 1 to 5 stars.")
        if partner_rating is not None and not 1 <= partner_rating <= 5:
            errors.append("Partner rating must be between 1 and 5.")
        if order.delivery_partner_id and partner_rating is None:
            errors.append("Please rate your delivery partner.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            comment = (request.form.get("comment") or "").strip()[:1000]
            entry = Feedback(
                order_id=order.id,
                customer_id=_user().id,
                restaurant_id=order.restaurant_id,
                partner_id=order.delivery_partner_id,
                restaurant_rating=restaurant_rating,
                partner_rating=partner_rating,
                comment=comment,
            )
            db.session.add(entry)
            _apply_rating(order.restaurant, restaurant_rating)
            profile = order.delivery_partner.partner_profile if order.delivery_partner else None
            if profile and partner_rating:
                _apply_partner_rating(profile, partner_rating)
            if order.delivery_partner_id and partner_rating:
                notify(
                    order.delivery_partner_id,
                    f"You received {partner_rating}\u2605",
                    f"{order.customer.name} rated the delivery of {order.order_number}.",
                    "feedback",
                    url_for("delivery.history"),
                )
            db.session.commit()
            flash("Thanks for your feedback!", "success")
            return redirect(url_for("customer.order_detail", order_id=order.id))

    return render_template("customer/feedback.html", order=order)


def _apply_rating(restaurant: Restaurant, rating: int) -> None:
    count = restaurant.rating_count or 0
    avg = restaurant.rating_avg or 0.0
    restaurant.rating_count = count + 1
    restaurant.rating_avg = round((avg * count + rating) / (count + 1), 2)


def _apply_partner_rating(profile, rating: int) -> None:
    count = profile.rating_count or 0
    avg = profile.rating_avg or 0.0
    profile.rating_count = count + 1
    profile.rating_avg = round((avg * count + rating) / (count + 1), 2)
