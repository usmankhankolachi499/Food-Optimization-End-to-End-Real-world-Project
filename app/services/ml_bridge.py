"""Bridge to the machine-learning / data module (built separately).

The SRS keeps the ML pipeline out of the web tier. If a compatible module
(for example ``ml.predictor``) is present on ``PYTHONPATH`` and exposes a
``predict_eta(features: dict) -> float | dict`` function, it is used
automatically. Otherwise the web application falls back to a transparent,
deterministic ETA heuristic so that every screen remains functional.

Expected feature dictionary::

    {
        "distance_km": 4.2,
        "prep_time_min": 25,
        "item_count": 3,
        "traffic_factor": 1.15,
        "hour_of_day": 19,
        "weather": "clear",          # optional
    }
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from flask import current_app

log = logging.getLogger(__name__)

_cached_module = None
_cache_key = None


def _load_predictor():
    global _cached_module, _cache_key
    if not current_app.config.get("ML_ENABLED", True):
        return None
    module_name = current_app.config.get("ML_MODULE", "ml.predictor")
    if _cache_key == module_name:
        return _cached_module
    _cache_key = module_name
    try:
        _cached_module = importlib.import_module(module_name)
        if not hasattr(_cached_module, "predict_eta"):
            _cached_module = None
    except Exception:  # ModuleNotFoundError and any model-loading error
        _cached_module = None
    return _cached_module


def ml_available() -> bool:
    return _load_predictor() is not None


def predict_eta(
    distance_km: float,
    prep_time_min: int,
    item_count: int,
    traffic_factor: float | None = None,
    hour_of_day: int | None = None,
) -> dict[str, Any]:
    """Return ``{"minutes": int, "source": "ml"|"heuristic"}``."""
    from datetime import datetime

    from .settings import get_float, get_int

    traffic_factor = (
        float(traffic_factor) if traffic_factor is not None else get_float("traffic_factor", 1.15)
    )
    speed = max(8.0, get_float("avg_speed_kmph", 24.0))
    buffer_min = get_int("prep_buffer_min", 10)
    hour_of_day = hour_of_day if hour_of_day is not None else datetime.now().hour

    features = {
        "distance_km": round(float(distance_km or 0), 3),
        "prep_time_min": int(prep_time_min or 0),
        "item_count": int(item_count or 1),
        "traffic_factor": round(float(traffic_factor), 3),
        "hour_of_day": int(hour_of_day),
    }

    predictor = _load_predictor()
    if predictor is not None:
        try:
            result = predictor.predict_eta(features)
            if isinstance(result, dict):
                minutes = result.get("minutes") or result.get("eta_minutes") or result.get("prediction")
            else:
                minutes = result
            minutes = int(round(float(minutes)))
            if 1 <= minutes <= 300:
                return {"minutes": minutes, "source": "ml"}
        except Exception as exc:  # never break the request because of a model
            log.warning("ML ETA prediction failed, using heuristic: %s", exc)

    travel_min = (max(0.0, float(distance_km or 0)) / speed) * 60 * max(1.0, traffic_factor)
    minutes = int(round(max(5, prep_time_min or 0) + travel_min + buffer_min))
    return {"minutes": max(5, min(300, minutes)), "source": "heuristic"}


def predict_partner_score(distance_km: float, workload: int, rating: float) -> float | None:
    """Optional ML ranking hook for the order-assignment module.

    Falls back to ``None`` so the deterministic distance/workload ranking in
    :mod:`app.services.assignment` is used.
    """
    predictor = _load_predictor()
    if predictor is None or not hasattr(predictor, "score_partner"):
        return None
    try:
        return float(
            predictor.score_partner(
                {
                    "distance_km": round(float(distance_km), 3),
                    "workload": int(workload),
                    "rating": float(rating or 0),
                }
            )
        )
    except Exception as exc:
        log.warning("ML partner scoring failed: %s", exc)
        return None
