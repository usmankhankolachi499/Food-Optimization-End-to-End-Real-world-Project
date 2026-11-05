"""Data pipeline service (SRS 3.10 & 3.11).

Gives the admin panel a single view over the data engineering side of the
project:

* inventory of the ``data/`` folder (raw CSV / JSONL sources, ML dataset),
* ingestion status for the SQL Server (T-SQL) and MongoDB stores,
* a repeatable ``run_validation()`` quality report over the ingested rows.

Validation is read-only; it flags suspicious rows that the cleaning stage of
the ingestion scripts would remove or repair.
"""
from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal

from ..extensions import db
from ..models import (
    DeliveryPartnerProfile,
    Feedback,
    MenuItem,
    Order,
    Restaurant,
    User,
    CustomerProfile,
)
from ..utils import utcnow

_DATA_DIRS = ("raw", "cleaned", "ml", "mongodb", "sql_server")


def _data_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


def source_files() -> list[dict]:
    """Inventory of data/ source files (the deliverable dataset folders)."""
    root = _data_root()
    files: list[dict] = []
    if not os.path.isdir(root):
        return files
    for folder in sorted(os.listdir(root)):
        folder_path = os.path.join(root, folder)
        if not os.path.isdir(folder_path):
            continue
        entries = []
        for name in sorted(os.listdir(folder_path))[:12]:
            path = os.path.join(folder_path, name)
            if os.path.isfile(path):
                size_kb = max(1, os.path.getsize(path) // 1024)
                entries.append({"name": name, "kb": size_kb})
        files.append({"folder": folder, "files": entries})
    return files


def sql_status() -> dict:
    """Row counts of every ingested SQL Server table."""
    from ..extensions import _TABLES  # name -> model

    tables: dict[str, int] = {}
    for name, model in sorted(_TABLES.items()):
        try:
            tables[name] = model.query.count()
        except Exception:  # pragma: no cover
            tables[name] = -1
    engine = ""  # filled by caller
    return {"tables": tables, "engine": engine}


def mongo_status() -> dict:
    """MongoDB mirror status (optional high-volume tracking store)."""
    from .tracking import _mongo_collection

    collection = _mongo_collection()
    if collection is None:
        return {"enabled": False, "collections": {}}
    wanted = ["location_logs", "tracking_events", "traffic_data"]
    try:
        database = collection.database
        real = set(database.list_collection_names())
        counts = {name: database[name].count_documents({}) for name in wanted if name in real}
    except Exception:  # pragma: no cover
        return {"enabled": True, "collections": {}}
    return {"enabled": True, "collections": counts}


def run_validation() -> dict:
    """SRS 3.10 - validate the ingested rows and report issues per table."""
    issues: dict[str, list[str]] = {}

    counts = (
        db.session.query(Order.order_number, db.func.count(Order.id))
        .group_by(Order.order_number)
        .all()
    )
    issues["orders"] = [
        f"duplicate order number {number} x{count}"
        for number, count in counts
        if isinstance(number, str) and count and int(count) > 1
    ]
    for order in Order.query.filter(Order.delivery_lat.is_(None) | Order.delivery_lng.is_(None)).limit(25).all():
        issues["orders"].append(f"{order.order_number}: missing delivery coordinates")
    for order in Order.query.filter(Order.distance_km <= 0.0).limit(25).all():
        issues["orders"].append(f"{order.order_number}: distance_km <= 0")

    for restaurant in Restaurant.query.limit(500).all():
        lat = restaurant.latitude
        lng = restaurant.longitude
        if lat is None or lng is None:
            continue
        if not (20.0 <= lat <= 35.0) or not (60.0 <= lng <= 75.0):
            issues["restaurants"].append(
                f"{restaurant.name}: coordinates {lat}, {lng} are outside Pakistan"
            )

    for item in MenuItem.query.filter(MenuItem.price <= 0).limit(25).all():
        issues["menu_items"].append(f"{item.name}: price <= 0")
    for item in MenuItem.query.filter(
        db.or_(MenuItem.prep_time_min <= 0, MenuItem.prep_time_min > 180)
    ).limit(25).all():
        issues["menu_items"].append(f"{item.name}: prep_time_min out of range")

    for feedback in Feedback.query.filter(
        db.or_(Feedback.restaurant_rating < 1, Feedback.restaurant_rating > 5)
    ).limit(25).all():
        issues["feedback"].append(f"order #{feedback.order_id}: restaurant_rating out of range")
    orphans = Feedback.query.filter(Feedback.partner_id.is_(None), Feedback.partner_rating.isnot(None)).limit(25).all()
    for feedback in orphans:
        issues["feedback"].append(f"order #{feedback.order_id}: partner_rating without a partner")

    for user in User.query.filter(
        ~(User.role.in_(["customer", "delivery", "admin"]))
    ).limit(25).all():
        issues["users"].append(f"{user.username}: unknown role '{user.role}'")

    thresholds = utcnow() - timedelta(days=180)
    stale = Order.query.filter(
        Order.status.in_(["placed", "confirmed", "prepared", "dispatched"]),
        Order.placed_at < thresholds,
    ).count()
    if stale:
        issues["orders"].append(f"{stale} stale active order(s) older than 180 days")

    quality: dict[str, dict] = {}
    checks = {
        "orders": (Order.query.count(), len(issues["orders"])),
        "restaurants": (Restaurant.query.count(), len(issues.get("restaurants", []))),
        "menu_items": (MenuItem.query.count(), len(issues.get("menu_items", []))),
        "users": (User.query.count(), len(issues.get("users", []))),
        "feedback": (Feedback.query.count(), len(issues.get("feedback", []))),
        "delivery_partner_profiles": (
            DeliveryPartnerProfile.query.count(),
            0,
        ),
        "customer_profiles": (CustomerProfile.query.count(), 0),
    }
    for table, (rows, flagged) in checks.items():
        quality[table] = {
            "rows": rows,
            "flagged": flagged,
            "clean_percent": round((rows - flagged) / rows * 100, 1) if rows else 100.0,
        }
    # addresses are expected to be filled for customers
    missing_address = CustomerProfile.query.filter(
        CustomerProfile.address.is_(None) | (CustomerProfile.address == "")
    ).count()
    customer_rows = checks["customer_profiles"][0]
    if missing_address and customer_rows:
        flagged = checks["customer_profiles"][1] + missing_address
        checks["customer_profiles"] = (customer_rows, flagged)
        quality["customer_profiles"] = {
            "rows": customer_rows,
            "flagged": flagged,
            "clean_percent": round((customer_rows - flagged) / customer_rows * 100, 1),
        }
        issues["customer_profiles"] = [f"{missing_address} profile(s) without an address"]

    issues = {k: v for k, v in issues.items() if v}
    return {
        "quality": quality,
        "issues": issues,
        "generated_at": utcnow(),
    }
