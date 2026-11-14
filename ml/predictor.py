"""
ML predictor - trained model ko load kar ke ETA nikalta hai.

Files: delivery_time_model.pkl + model_features.pkl (project root).
Web tier isay app.services.ml_bridge ke through call karta hai:

    predict_eta(features) -> {"minutes": float, "source": "ml"}

Categorical values one-hot encoding mein convert hoti hain
(training pipeline wale hi column names use hote hain).
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

# P(traffic_level | hour) - training dataset ke TRAIN split (seed 42) se
# derived. Serving par asli traffic nahi hoti, ye probabilities estimate
# hain - aur training mein bhi traffic inhi probabilities se aati hai,
# is liye train = serve (no skew): benchmark aur production EK number.
TRAFFIC_PROBS_BY_HOUR = {
    0: (0.995, 0.005, 0.000), 1: (1.000, 0.000, 0.000), 2: (1.000, 0.000, 0.000),
    3: (1.000, 0.000, 0.000), 4: (1.000, 0.000, 0.000), 5: (1.000, 0.000, 0.000),
    6: (1.000, 0.000, 0.000), 7: (0.637, 0.363, 0.000), 8: (0.006, 0.691, 0.304),
    9: (0.000, 0.426, 0.574), 10: (0.232, 0.757, 0.011), 11: (0.122, 0.851, 0.027),
    12: (0.007, 0.528, 0.465), 13: (0.000, 0.156, 0.844), 14: (0.021, 0.711, 0.268),
    15: (0.301, 0.694, 0.005), 16: (0.136, 0.856, 0.008), 17: (0.002, 0.313, 0.685),
    18: (0.000, 0.065, 0.935), 19: (0.000, 0.009, 0.991), 20: (0.000, 0.018, 0.982),
    21: (0.000, 0.109, 0.891), 22: (0.046, 0.758, 0.196), 23: (0.657, 0.343, 0.000),
}

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
    """Bridge contract: {"minutes": float, "source": "ml"}.

    Rider-side features (p2r, workload, vehicle, experience) checkout ke
    waqt available nahi hote - tab defaults use hote hain. Assignment ke
    baad routing inhe REAL values ke sath dobara call karta hai.
    """
    now = datetime.now()
    hour = int(features.get("hour_of_day") or now.hour)
    distance = float(features.get("distance_km") or 0.0)
    prep = float(features.get("prep_time_min") or DEFAULTS["prep_time_min"])
    p2r = float(
        features.get("partner_to_restaurant_km") or DEFAULTS["partner_to_restaurant_km"]
    )
    # traffic: training jaisi hi hour-based probabilities (train = serve)
    p_low, p_med, p_high = TRAFFIC_PROBS_BY_HOUR.get(hour, (0.34, 0.34, 0.32))

    minutes = estimate({
        "distance_km": distance,
        "partner_to_restaurant_km": p2r,
        "prep_time_min": prep,
        "order_hour": hour,
        "day_of_week": now.weekday(),               # dataset convention: Mon=0..Sun=6
        "is_weekend": 1 if now.weekday() >= 5 else 0,
        "is_peak": 1 if (7 <= hour <= 10) or (17 <= hour <= 21) else 0,
        "is_late_night": 1 if hour <= 4 else 0,
        "traffic_level_low": p_low,
        "traffic_level_medium": p_med,
        "traffic_level_high": p_high,
        "partner_current_orders": int(
            features.get("partner_current_orders") or DEFAULTS["partner_current_orders"]
        ),
        "vehicle_type": features.get("vehicle_type") or "Bike",
        "experience_months": float(
            features.get("experience_months") or DEFAULTS["experience_months"]
        ),
        "cuisine": features.get("cuisine") or "Fast Food",
        "restaurant_quality": float(
            features.get("restaurant_quality") or DEFAULTS["restaurant_quality"]
        ),
        "weather_rain": 1 if (features.get("weather") == "rain") else 0,
        "distance_speed_ratio": round(distance / max(1.0, p2r), 2),
        "batched": int(features.get("batched") or 0),
    })
    return {"minutes": minutes, "source": "ml"}
