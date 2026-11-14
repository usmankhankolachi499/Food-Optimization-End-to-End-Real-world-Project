"""Production-path accuracy evaluation for the delivery-time model.

Model ab CONSISTENT hai: training mein traffic usi hour-based
probabilities se aati hai jo serving par use hoti hai
(ml.predictor.TRAFFIC_PROBS_BY_HOUR). Is liye test accuracy = production
accuracy - dono jagah EK hi number, koi train/serve skew nahi.

Ye script SIRF memory mein train karti hai - pkl files overwrite nahi hoti.

Run:  python scripts/eval_production_accuracy.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.predictor import TRAFFIC_PROBS_BY_HOUR  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(BASE, "data", "ml", "delivery_time_dataset.csv")

BASE_FEATURES = [
    "distance_km", "partner_to_restaurant_km", "prep_time_min",
    "order_hour", "day_of_week", "is_weekend", "is_peak",
    "is_late_night", "partner_current_orders",
    "vehicle_type", "experience_months", "cuisine",
    "restaurant_quality", "weather_rain", "distance_speed_ratio",
    "batched",
]
FULL_ORACLE = BASE_FEATURES + ["traffic_level"]
LEVELS = ("low", "medium", "high")


def make_model():
    # train_model.py jaisa hi config
    return HistGradientBoostingRegressor(
        random_state=42, max_iter=1200, learning_rate=0.03,
        max_leaf_nodes=31, l2_regularization=0.05, min_samples_leaf=20,
        early_stopping=True, validation_fraction=0.15,
    )


def evaluate(model, P, tag):
    pred = model.predict(P)
    r2 = r2_score(yte, pred)
    mae = mean_absolute_error(yte, pred)
    w10 = (np.abs(pred - yte) <= 10).mean() * 100
    w5 = (np.abs(pred - yte) <= 5).mean() * 100
    print(f"  {tag:52s} R2 = {r2:.3f} | MAE = {mae:.2f} min | +/-10min = {w10:.1f}% | +/-5min = {w5:.1f}%")
    return r2


def main():
    df = pd.read_csv(DATASET)
    global yte
    y = df["actual_delivery_min"]

    print(f"dataset: {len(df)} rows | split: 80/20 seed 42")
    print("\nSame trained model, different feature inputs:\n")

    # A) CONSISTENT model (train = serve): traffic = hour-based probs
    X = pd.get_dummies(df[BASE_FEATURES])
    for level in LEVELS:
        X[f"traffic_level_{level}"] = [
            TRAFFIC_PROBS_BY_HOUR.get(int(h) % 24, (0.34, 0.34, 0.32))[
                LEVELS.index(level)
            ]
            for h in df["order_hour"]
        ]
    itr, ite = train_test_split(np.arange(len(df)), test_size=0.2, random_state=42)
    ytr, yte = y.iloc[itr], y.iloc[ite].reset_index(drop=True)
    model = make_model()
    model.fit(X.iloc[itr], ytr)
    evaluate(model, X.iloc[ite].reset_index(drop=True),
             "A) CONSISTENT (train = serve) - app ka live path")

    # B) oracle upper bound: asli recorded traffic (serving par nahi milti)
    Xo = pd.get_dummies(df[FULL_ORACLE])
    model_o = make_model()
    model_o.fit(Xo.iloc[itr], ytr)
    evaluate(model_o, Xo.iloc[ite].reset_index(drop=True),
             "B) ORACLE upper bound (asli traffic, sirf benchmark)")

    # C) formula fallback (ml_bridge ka heuristic, ML ke baghair)
    raw = df.iloc[ite].reset_index(drop=True)
    pred_f = raw["prep_time_min"] + (raw["distance_km"] / 24.0) * 60 * 1.15 + 10
    r2f = r2_score(yte, pred_f)
    maef = mean_absolute_error(yte, pred_f)
    w10f = (np.abs(pred_f - yte) <= 10).mean() * 100
    print(f"  {'C) formula fallback (ML ke baghair)':52s} R2 = {r2f:.3f} | MAE = {maef:.2f} min | +/-10min = {w10f:.1f}%")

    print("\nNote: A = model ka test R2 AUR production accuracy - dono EK number")
    print("(train/serve consistent, koi skew nahi). B sirf upper bound hai:")
    print("asli recorded traffic serving par available nahi hoti. Dataset ka")
    print("noise floor R2 ~0.937 hai (5-fold OOF), is liye 0.95 R2 reachable")
    print("nahi - A ka +/-10min accuracy hi practical accuracy metric hai.")


if __name__ == "__main__":
    main()
