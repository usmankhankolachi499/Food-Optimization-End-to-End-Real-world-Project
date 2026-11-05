"""In-app notifications (SRS: Alert & Notification System)."""
from __future__ import annotations

from typing import Iterable, Optional

from ..extensions import db
from ..models import Notification, Order, User, ROLE_ADMIN


def notify(
    user_id: int,
    title: str,
    message: str = "",
    category: str = "system",
    link: Optional[str] = None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        title=title[:140],
        message=message[:500],
        category=category,
        link=link,
    )
    db.session.add(row)
    return row


def notify_user(
    user: Optional[User],
    title: str,
    message: str = "",
    category: str = "system",
    link: Optional[str] = None,
) -> Optional[Notification]:
    if user is None:
        return None
    return notify(user.id, title, message, category, link)


def notify_roles(
    roles: Iterable[str],
    title: str,
    message: str = "",
    category: str = "system",
    link: Optional[str] = None,
) -> int:
    users = User.query.filter(User.role.in_(list(roles)), User.is_active.is_(True)).all()
    for user in users:
        notify(user.id, title, message, category, link)
    return len(users)


def notify_admins(title: str, message: str = "", category: str = "system", link: Optional[str] = None) -> int:
    return notify_roles([ROLE_ADMIN], title, message, category, link)


def notify_order_status(order: Order) -> None:
    """Create the customer-facing message for the order's current status."""
    from flask import url_for

    link = url_for("customer.order_detail", order_id=order.id)
    messages = {
        "placed": ("Order placed", f"{order.order_number} has been received."),
        "confirmed": ("Order confirmed", f"{order.restaurant.name} confirmed {order.order_number}."),
        "prepared": ("Food prepared", f"{order.order_number} is packed and ready."),
        "dispatched": ("Out for delivery", f"Your order {order.order_number} is on the way."),
        "delivered": ("Delivered", f"{order.order_number} was delivered. Enjoy your meal!"),
        "cancelled": ("Order cancelled", f"{order.order_number} was cancelled."),
    }
    title, message = messages.get(order.status, ("Order update", f"{order.order_number} was updated."))
    notify(order.customer_id, title, message, "order", link)
