"""Small, dependency-free helpers shared across the application."""
from __future__ import annotations

import math
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


def utcnow() -> datetime:
    """Naive UTC timestamp (safe for SQLite and cross-database use)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def as_decimal(value, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_money(value) -> str:
    """Pakistani-rupee presentation helper used by Jinja filters."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Rs 0"
    # PKR menus almost always price in whole rupees; show paisa only when needed
    if abs(number - round(number)) < 0.005:
        return f"Rs {number:,.0f}"
    return f"Rs {number:,.2f}"


def format_datetime(value: Optional[datetime], fmt: str = "%d %b %Y, %I:%M %p") -> str:
    if not value:
        return "\u2014"
    return value.strftime(fmt)


def format_time(value) -> str:
    if not value:
        return "\u2014"
    return value.strftime("%I:%M %p")


def time_ago(value: Optional[datetime]) -> str:
    if not value:
        return "\u2014"
    seconds = max(0, int((utcnow() - value).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    return f"{seconds // 86400} day(s) ago"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return 0.0
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return round(2 * radius * math.asin(math.sqrt(a)), 3)


def generate_order_number() -> str:
    stamp = utcnow().strftime("%y%m%d")
    suffix = "".join(secrets.choice("0123456789") for _ in range(4))
    return f"FD{stamp}{suffix}"


def validate_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email.strip()))


def validate_phone(phone: str) -> bool:
    return bool(phone and PHONE_RE.match(phone.strip()))


def safe_next_url(target: Optional[str]) -> Optional[str]:
    """Only allow local redirects (prevents open-redirect abuse)."""
    if not target:
        return None
    target = target.strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return None


def parse_coordinate(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (-180 <= number <= 180):
        return None
    return number


def is_lat(value) -> bool:
    try:
        return -90 <= float(value) <= 90
    except (TypeError, ValueError):
        return False


def is_lng(value) -> bool:
    try:
        return -180 <= float(value) <= 180
    except (TypeError, ValueError):
        return False
