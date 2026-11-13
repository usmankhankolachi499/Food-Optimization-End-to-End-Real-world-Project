"""Data cleaning step (SRS 3.10): raw -> cleaned.

Reads data/raw/orders_raw.csv + location_logs_raw.jsonl, fixes common
issues (duplicates, invalid coordinates, negative distances, missing
values) and writes the cleaned deliverables:

    data/cleaned/orders_clean.csv
    data/cleaned/location_logs_clean.jsonl
    data/cleaned/processing_report.json

Run:  python scripts/clean_data.py
"""
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

RAW = os.path.join(config.DATA_DIR, "raw")
CLEAN = os.path.join(config.DATA_DIR, "cleaned")
os.makedirs(CLEAN, exist_ok=True)

EARTH_RADIUS_KM = 6371.0
VALID_LAT = (-90.0, 90.0)
VALID_LNG = (-180.0, 180.0)


def _clean_orders() -> dict:
    src = os.path.join(RAW, "orders_raw.csv")
    dst = os.path.join(CLEAN, "orders_clean.csv")
    with open(src, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    total_in = len(rows)

    # 1) duplicate order_ids nikal do (pehli row rakhte hain)
    seen_ids, unique_rows, dupes = set(), [], 0
    for row in rows:
        oid = row["order_id"]
        if oid in seen_ids:
            dupes += 1
            continue
        seen_ids.add(oid)
        unique_rows.append(row)

    # 2) numeric fields ki safai
    removed, fixed = [], 0
    kept = []
    for row in unique_rows:
        try:
            distance = float(row["distance_km"]) if row["distance_km"] else None
            prep = float(row["prep_time_min"]) if row["prep_time_min"] else None
        except ValueError:
            distance = prep = None

        if distance is not None and distance < 0:
            removed.append("negative distance_km")
            continue  # negative distance ka data barbaad - drop
        if distance is None:
            # delivered rows bina distance ke theek nahi ho sakte
            if row["status"] == "delivered":
                removed.append("missing distance_km")
                continue
            row["distance_km"] = ""
        if prep is None and row["status"] == "delivered":
            # delivered order ki median prep time se imputation
            row["prep_time_min"] = "17.0"
            fixed += 1

        # timestamps ki aakhri safai (trailing nanoseconds normalize)
        for col in ("accepted_time", "prepared_time", "dispatched_time", "delivered_time"):
            if row[col]:
                row[col] = row[col].split(".")[0] if row[col].count(".") and "." in row[col] and len(row[col].split(".")[1]) > 6 else row[col]
        kept.append(row)

    with open(dst, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(kept[0].keys()))
        writer.writeheader()
        writer.writerows(kept)

    return {
        "input_rows": total_in,
        "output_rows": len(kept),
        "duplicates_removed": dupes,
        "rows_removed": len(removed),
        "imputed_prep_time": fixed,
    }


def _clean_location_logs() -> dict:
    src = os.path.join(RAW, "location_logs_raw.jsonl")
    dst = os.path.join(CLEAN, "location_logs_clean.jsonl")

    total_in, invalid_coords, missing_order, out = 0, 0, 0, []
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total_in += 1
            rec = json.loads(line)
            # raw files mein lat/lon (short) names use hote hain
            lat, lng = rec.get("lat", rec.get("latitude")), rec.get("lon", rec.get("longitude"))
            if lat is None or lng is None:
                invalid_coords += 1
                continue
            if not (VALID_LAT[0] <= float(lat) <= VALID_LAT[1]):
                invalid_coords += 1
                continue
            if not (VALID_LNG[0] <= float(lng) <= VALID_LNG[1]):
                invalid_coords += 1
                continue
            # Karachi ke bahar ke GPS pings bhi invalid hain (approx bounding box)
            if not (23.7 <= float(lat) <= 25.2 and 66.6 <= float(lng) <= 68.0):
                invalid_coords += 1
                continue
            if not rec.get("order_id"):
                missing_order += 1
                continue
            out.append(rec)

    with open(dst, "w", encoding="utf-8") as fh:
        for rec in out:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return {
        "input_rows": total_in,
        "output_rows": len(out),
        "rows_removed": total_in - len(out),
        "invalid_coordinates_removed": invalid_coords,
    }


def main() -> None:
    print("cleaning data/raw -> data/cleaned ...")
    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "steps": {
            "orders": _clean_orders(),
            "location_logs": _clean_location_logs(),
        },
        "notes": [
            "duplicates dropped by order_id",
            "negative distance_km rows dropped",
            "delivered rows missing prep_time imputed with median 17.0",
            "GPS pings outside Karachi bounding box removed",
        ],
    }
    out_path = os.path.join(CLEAN, "processing_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report["steps"], indent=2))
    print(f"report: {out_path}")


if __name__ == "__main__":
    main()
