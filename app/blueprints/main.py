"""Public pages: landing, restaurant discovery and menu browsing."""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from ..auth import get_current_user
from ..extensions import db
from ..models import Feedback, MenuItem, Restaurant
from ..services.cart import get_cart

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    user = get_current_user()
    if user is not None:
        return redirect(url_for(user.dashboard_endpoint))
    restaurants = (
        Restaurant.query.filter_by(is_active=True)
        .order_by(Restaurant.rating_avg.desc(), Restaurant.name.asc())
        .limit(6)
        .all()
    )
    cuisines = [
        row[0]
        for row in db.session.query(Restaurant.cuisine)
        .filter(Restaurant.is_active.is_(True), Restaurant.cuisine.isnot(None))
        .distinct()
        .order_by(Restaurant.cuisine)
        .limit(8)
        .all()
        if row[0]
    ]
    return render_template("main/index.html", restaurants=restaurants, cuisines=cuisines)


@bp.get("/restaurants")
def restaurants():
    q = (request.args.get("q") or "").strip()
    cuisine = (request.args.get("cuisine") or "").strip()
    city = (request.args.get("city") or "").strip()
    sort = request.args.get("sort", "rating")
    only_open = request.args.get("open") == "1"
    page = max(1, request.args.get("page", 1, type=int))

    query = Restaurant.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Restaurant.name.ilike(like),
                Restaurant.cuisine.ilike(like),
                Restaurant.city.ilike(like),
                Restaurant.description.ilike(like),
            )
        )
    if cuisine:
        query = query.filter(Restaurant.cuisine == cuisine)
    if city:
        query = query.filter(Restaurant.city == city)

    if sort == "name":
        query = query.order_by(Restaurant.name.asc())
    elif sort == "new":
        query = query.order_by(Restaurant.created_at.desc())
    else:
        query = query.order_by(Restaurant.rating_avg.desc(), Restaurant.name.asc())

    pagination = query.paginate(page=page, per_page=9, error_out=False)
    items = pagination.items
    if only_open:
        items = [item for item in items if item.is_open_now]

    cuisines = sorted(
        {
            row[0]
            for row in db.session.query(Restaurant.cuisine)
            .filter(Restaurant.is_active.is_(True), Restaurant.cuisine.isnot(None))
            .distinct()
            .all()
            if row[0]
        }
    )
    cities = sorted(
        {
            row[0]
            for row in db.session.query(Restaurant.city)
            .filter(Restaurant.is_active.is_(True), Restaurant.city.isnot(None))
            .distinct()
            .all()
            if row[0]
        }
    )
    return render_template(
        "main/restaurants.html",
        restaurants=items,
        pagination=pagination,
        cuisines=cuisines,
        cities=cities,
        filters={"q": q, "cuisine": cuisine, "city": city, "sort": sort, "open": only_open},
    )


@bp.get("/restaurants/<int:restaurant_id>")
def restaurant_detail(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None or not restaurant.is_active:
        abort(404)
    menu_items = (
        MenuItem.query.filter_by(restaurant_id=restaurant.id)
        .order_by(MenuItem.category.asc(), MenuItem.name.asc())
        .all()
    )
    grouped: dict[str, list[MenuItem]] = {}
    for item in menu_items:
        grouped.setdefault(item.category or "Menu", []).append(item)
    feedback = (
        Feedback.query.filter_by(restaurant_id=restaurant.id)
        .order_by(Feedback.created_at.desc())
        .limit(6)
        .all()
    )
    cart = get_cart()
    cart_quantities = {
        entry["item"].id: entry["quantity"] for entry in cart["items"]
    } if cart["restaurant"] and cart["restaurant"].id == restaurant.id else {}
    return render_template(
        "main/restaurant_detail.html",
        restaurant=restaurant,
        grouped_menu=grouped,
        feedback=feedback,
        cart_quantities=cart_quantities,
    )


@bp.get("/about")
def about():
    return render_template("main/about.html")
