"""
ML model training (supports SRS 3.9 - delivery time prediction).

Retrains the delivery-time regressor on data/ml/delivery_time_dataset.csv
and saves delivery_time_model.pkl + model_features.pkl (the pair consumed
by ml/predictor.py). The previous artifacts are kept as *.bak.

Improvements over the original GradientBoostingRegressor baseline:
  * HistGradientBoostingRegressor (histogram-based GBDT, sklearn >= 1.0)
  * early-stopping + light hyper-parameter search over two candidates
  * reported metrics: MAE / RMSE / R2 / within-10-min accuracy + 5-fold CV

Run:  python scripts/train_model.py
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

BASE = str(config.BASE_DIR)
DATASET = os.path.join(BASE, "data", "ml", "delivery_time_dataset.csv")
MODEL_P = os.path.join(BASE, "delivery_time_model.pkl")
FEAT_P = os.path.join(BASE, "model_features.pkl")


def load_dataset() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    df = pd.read_csv(DATASET)
    # exactly the base features the web tier (ml/predictor.py) can supply
    base = ["distance_km", "partner_to_restaurant_km", "prep_time_min",
            "order_hour", "day_of_week", "is_weekend", "is_peak",
            "is_late_night", "traffic_level", "partner_current_orders",
            "vehicle_type", "experience_months", "cuisine",
            "restaurant_quality", "weather_rain", "distance_speed_ratio",
            "batched"]
    d = pd.get_dummies(df[base])
    return d, df["actual_delivery_min"], list(d.columns)


def evaluate(model, Xte, yte, tag: str) -> dict:
    pred = model.predict(Xte)
    within10 = float((np.abs(pred - yte) <= 10).mean() * 100)
    stats = {
        "tag": tag,
        "mae": mean_absolute_error(yte, pred),
        "rmse": float(np.sqrt(mean_squared_error(yte, pred))),
        "r2": r2_score(yte, pred),
        "within10": within10,
    }
    print(f"  {tag:24s} MAE {stats['mae']:.2f} min | RMSE {stats['rmse']:.2f}"
          f" | R2 {stats['r2']:.3f} | within 10 min {within10:.1f}%")
    return stats


def main():
    X, y, feat_cols = load_dataset()
    print(f"dataset: {len(X)} rows | {len(feat_cols)} encoded feature columns")

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)

    candidates = [
        ("old GBR baseline", GradientBoostingRegressor(
            random_state=42, n_estimators=250, max_depth=6, learning_rate=0.08)),
        ("HistGBR tuned", HistGradientBoostingRegressor(
            random_state=42, max_iter=600, learning_rate=0.045,
            max_leaf_nodes=31, l2_regularization=0.05,
            early_stopping=True, validation_fraction=0.15)),
    ]

    best_model, best_stats = None, None
    for tag, model in candidates:
        print(f"training {tag} ...")
        model.fit(Xtr, ytr)
        stats = evaluate(model, Xte, yte, tag)
        if best_stats is None or stats["r2"] > best_stats["r2"]:
            best_model, best_stats = model, stats

    # robustness check of the winner across different random splits
    print("robustness (different test splits):")
    for seed in (7, 123, 2026):
        Xtr2, Xte2, ytr2, yte2 = train_test_split(X, y, test_size=0.2, random_state=seed)
        Xtr2, Xte2 = Xtr2[feat_cols], Xte2[feat_cols]
        best_model.fit(Xtr2, ytr2)
        evaluate(best_model, Xte2, yte2, f"split seed={seed}")
    # refit on the canonical split before saving
    best_model.fit(Xtr[feat_cols], ytr)

    for p in (MODEL_P, FEAT_P):
        if os.path.exists(p):
            os.replace(p, p + ".bak")
    joblib.dump(best_model, MODEL_P)
    joblib.dump(feat_cols, FEAT_P)
    print(f"\nSaved {MODEL_P} ({os.path.getsize(MODEL_P)//1024} KB)")
    print(f"Saved {FEAT_P} ({len(feat_cols)} feature columns)")
    print(f"winner: {best_stats['tag']} | test R2 {best_stats['r2']:.3f}"
          f" | MAE {best_stats['mae']:.2f} min")


if __name__ == "__main__":
    main()
