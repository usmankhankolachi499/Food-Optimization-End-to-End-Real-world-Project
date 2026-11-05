"""Session based shopping cart.

Only item ids and quantities are kept in the session; prices are always read
from the database so a cart can never be used to tamper with totals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from flask import session

from ..models import MenuItem
from ..utils import as_decimal

CART_KEY = "cart"
ZERO = Decimal("0.00")


def _raw() -> dict[str, int]:
    data = session.get(CART_KEY)
    if not isinstance(data, dict):
        return {}
    return {str(key): int(value) for key, value in data.items() if int(value) > 0}


def _save(data: dict[str, int]) -> None:
    session[CART_KEY] = {str(key): int(value) for key, value in data.items() if int(value) > 0}
    session.modified = True


def cart_count() -> int:
    return sum(_raw().values())


def clear_cart() -> None:
    session.pop(CART_KEY, None)
    session.modified = True


def add_item(item_id: int, quantity: int = 1) -> None:
    data = _raw()
    key = str(item_id)
    data[key] = min(99, data.get(key, 0) + max(1, quantity))
    _save(data)


def update_item(item_id: int, quantity: int) -> None:
    data = _raw()
    key = str(item_id)
    if quantity <= 0:
        data.pop(key, None)
    else:
        data[key] = min(99, quantity)
    _save(data)


def remove_item(item_id: int) -> None:
    data = _raw()
    data.pop(str(item_id), None)
    _save(data)


def cart_restaurant_id() -> Optional[int]:
    data = _raw()
    if not data:
        return None
    item = db_get_items(list(data.keys()))
    return item[0].restaurant_id if item else None


def db_get_items(item_ids: list[str]) -> list[MenuItem]:
    if not item_ids:
        return []
    ids = []
    for value in item_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    return MenuItem.query.filter(MenuItem.id.in_(ids)).all()


def get_cart() -> dict:
    """Return the validated cart with fresh prices from the database."""
    data = _raw()
    items: list[dict] = []
    subtotal = ZERO
    restaurant = None
    if data:
        menu_items = db_get_items(list(data.keys()))
        by_id = {item.id: item for item in menu_items}
        clean: dict[str, int] = {}
        for key, qty in data.items():
            item = by_id.get(int(key)) if key.isdigit() else None
            if item is None or not item.is_available or item.restaurant is None:
                continue
            if restaurant is None:
                restaurant = item.restaurant
            elif item.restaurant_id != restaurant.id:
                continue
            clean[str(item.id)] = qty
            line_total = as_decimal(item.price) * qty
            subtotal += line_total
            items.append(
                {
                    "item": item,
                    "quantity": qty,
                    "line_total": line_total,
                }
            )
        if clean != data:
            _save(clean)
    return {
        "items": items,
        "subtotal": subtotal,
        "restaurant": restaurant,
        "count": sum(entry["quantity"] for entry in items),
    }
