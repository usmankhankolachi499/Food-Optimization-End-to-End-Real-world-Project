"""
ML predictor module consumed by the web tier through ``app.services.ml_bridge``.

Loads the trained scikit-learn regressor shipped with the project
(``delivery_time_model.pkl`` + ``model_features.pkl`` at the project root -
these files are NOT part of the web app and are never rewritten by it) and
exposes:

    predict_eta(features: dict) -> {"minutes": float, "source": "ml"}

The expected feature dictionary (from ml_bridge) is translated into the
training feature set produced by scripts/train_model.py. Missing categorical
values are simply left as 0-hot (exactly like the original training pipeline).
"""
from __future__ import annotations

import importlib.util
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_HERE)
MODEL_PATH = os.path.join(_BASE_DIR, "delivery_time_model.pkl")
FEATURES_PATH = os.path.join(_BASE_DIR, "model_features.pkl")
DATASET_HINT = os.path.join(_BASE_DIR, "data", "ml", "delivery_time_dataset.csv")

DEFAULTS = {
    "partner_to_restaurant_km": 3.0,   # approx average pickup leg (km)
    "prep_time_min": 17.0,             # median kitchen prep from the dataset
    "partner_current_orders": 0,
    "experience_months": 15,
    "restaurant_quality": 4.0,
}
SPEED_KMH = {"low": 30, "medium": 22, "high": 14}

_lock = threading.Lock()
_model = None
_features = None
_pandas = None


def _load():
    """Lazy-load model artifacts once per process (thread-safe)."""
    global _model, _features, _pandas
    if _model is not None:
        return _model, _features
    with _lock:
        if _model is not None:
            return _model, _features
        import joblib

        _model = joblib.load(MODEL_PATH)
        _features = joblib.load(FEATURES_PATH)
        spec = importlib.util.find_spec("pandas")
        if spec is None:
            raise RuntimeError("pandas is required to build the feature row")
        _pandas = importlib.import_module("pandas")
        log.info("ML model loaded: %s (%d feature columns)",
                 os.path.basename(MODEL_PATH), len(_features))
    return _model, _features


def available() -> bool:
    try:
        _load()
        return True
    except Exception as exc:  # pragma: no cover - logged once
        log.warning("ML predictor unavailable (%s); the web tier falls back "
                    "to its deterministic heuristic.", exc)
        return False


def estimate(weighted: dict) -> float:
    """Predict delivery minutes for a base-feature dict (0-hot encoding like training)."""
    model, feats = _load()
    row = {c: 0 for c in feats}
    for key, value in weighted.items():
        if key in row:
            row[key] = value
        else:
            category = f"{key}_{value}"  # e.g. traffic_level -> traffic_level_low
            if category in row:
                row[category] = 1
    df = _pandas.DataFrame([row])[feats]
    prediction = model.predict(df)[0]
    return max(8.0, round(float(prediction), 1))


def _traffic_level(traffic_factor: float | None) -> str:
    factor = float(traffic_factor or 1.0)
    if factor <= 1.10:
        return "low"
    if factor <= 1.30:
        return "medium"
    return "high"


def predict_eta(features: dict) -> dict:
    """Bridge contract: {"minutes": float, "source": "ml"}."""
    now = datetime.now()
    hour = int(features.get("hour_of_day") or now.hour)
    distance = float(features.get("distance_km") or 0.0)
    prep = float(features.get("prep_time_min") or DEFAULTS["prep_time_min"])
    p2r = DEFAULTS["partner_to_restaurant_km"]

    minutes = estimate({
        "distance_km": distance,
        "partner_to_restaurant_km": p2r,
        "prep_time_min": prep,
        "order_hour": hour,
        "day_of_week": now.weekday(),               # dataset convention: Mon=0..Sun=6
        "is_weekend": 1 if now.weekday() >= 5 else 0,
        "is_peak": 1 if (7 <= hour <= 10) or (17 <= hour <= 21) else 0,
        "is_late_night": 1 if hour <= 4 else 0,
        "traffic_level": _traffic_level(features.get("traffic_factor")),
        "partner_current_orders": DEFAULTS["partner_current_orders"],
        "vehicle_type": "Bike",
        "experience_months": DEFAULTS["experience_months"],
        "cuisine": features.get("cuisine") or "Fast Food",
        "restaurant_quality": DEFAULTS["restaurant_quality"],
        "weather_rain": 1 if (features.get("weather") == "rain") else 0,
        "distance_speed_ratio": round(distance / max(1.0, p2r), 2),
        "batched": int(features.get("batched") or 0),
    })
    return {"minutes": minutes, "source": "ml"}
