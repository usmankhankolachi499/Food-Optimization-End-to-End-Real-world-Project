"""Runtime configuration stored in the database (Admin > Settings)."""
from __future__ import annotations

from . import __name__ as _pkg  # noqa: F401  (keeps package import semantics clear)
from ..extensions import db
from ..models import SystemSetting

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "base_delivery_fee": ("60", "Base delivery fee (Rs)"),
    "per_km_fee": ("25", "Delivery charge per kilometre (Rs)"),
    "avg_speed_kmph": ("20", "Average city speed used for ETA (km/h)"),
    "traffic_factor": ("1.35", "Karachi traffic multiplier applied to travel time (>= 1)"),
    "max_delivery_radius_km": ("14", "Maximum distance for automatic assignment (km)"),
    "max_orders_per_partner": ("3", "Maximum concurrent orders per partner (batch capacity)"),
    "prep_buffer_min": ("10", "Buffer minutes added after food preparation"),
    "partner_commission_percent": ("80", "Percent of delivery fee paid to the partner"),
    "auto_assign_orders": ("true", "Automatically assign confirmed orders to the best partner"),
}


def get_setting(key: str, default: str | None = None) -> str:
    row = SystemSetting.query.filter_by(key=key).first()
    if row is not None:
        return row.value
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key, ("", ""))[0]


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key))
    except (TypeError, ValueError):
        return default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(float(get_setting(key)))
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    return str(get_setting(key)).strip().lower() in {"1", "true", "yes", "on"}


def set_setting(key: str, value, description: str | None = None) -> SystemSetting:
    row = SystemSetting.query.filter_by(key=key).first()
    if row is None:
        row = SystemSetting(
            key=key,
            value=str(value),
            description=description or DEFAULT_SETTINGS.get(key, ("", ""))[1],
        )
        db.session.add(row)
    else:
        row.value = str(value)
        if description:
            row.description = description
    return row


def all_settings() -> dict[str, str]:
    values = {key: value for key, (value, _) in DEFAULT_SETTINGS.items()}
    values.update({row.key: row.value for row in SystemSetting.query.all()})
    return values


def ensure_defaults() -> None:
    from flask import current_app

    existing = {row.key for row in SystemSetting.query.all()}
    for key, (value, description) in DEFAULT_SETTINGS.items():
        if key not in existing:
            if key == "auto_assign_orders":
                value = (
                    "true"
                    if current_app.config.get("AUTO_ASSIGN_ORDERS", True)
                    else "false"
                )
            db.session.add(SystemSetting(key=key, value=value, description=description))
    db.session.commit()
