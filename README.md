# Food Delivery Optimization System — MOON Light

Aptech eProject — a complete, real-world food delivery platform localized for
**Karachi, Pakistan**.

The system connects customers, restaurants, and delivery partners on one
platform. It predicts delivery times using Machine Learning, assigns orders
to the best rider automatically, optimizes delivery routes, and tracks every
order live on a map.

---

## Key Features

### Customer Side
- Browse 12 Karachi restaurants with real photos and 125+ menu items
- Cart with add, update, and remove items
- Live ML-based delivery time prediction at checkout
- Real-time order tracking on an interactive map
- Order history, order cancel, and post-delivery feedback

### Admin Side
- Live dashboard: orders, revenue, active riders, live order feed
- One-click **Assign All** — assigns every pending order to the best rider
- **Auto-hire** — new riders are hired automatically when order volume grows
- Smart order assignment (distance + workload + ML score)
- Route optimizer with traffic-aware batch routing
- Analytics charts, CSV reports, audit trail, and system settings

### Delivery Partner Side
- Live delivery requests and earnings in PKR
- Accept orders, update location, change order status
- Availability toggle and delivery history

### Live Demo Simulator
- Places 2 new orders every minute so the platform always shows live activity
- Orders move through the full lifecycle: confirmed → prepared → dispatched → delivered
- Can be turned on/off from admin settings

### Machine Learning
- Model: HistGradientBoostingRegressor (scikit-learn)
- Trained on 13,000+ delivery records with 28 features
- **Accuracy (test = production, EK hi number): R² 0.921 (~92%)**,
  MAE ~3.68 min, 93.7% of predictions within ±10 min
  (held-out 20% test set, multi-split range 0.912–0.919)
- **No train/serve skew:** traffic is estimated the SAME way during
  training and serving (dataset-derived hour-probability table in
  `ml/predictor.TRAFFIC_PROBS_BY_HOUR`), so the benchmark score and the
  live app score are identical — there is no "offline vs production"
  accuracy gap by design.
- Oracle reference: with recorded real traffic (not available at serving
  time) the same algorithm measures R² 0.937 — that is the dataset's
  noise floor (5-fold OOF), so ~0.92 is the maximum honest live number.
  Reproduce: `python scripts/eval_production_accuracy.py`
- The delivery partner is assigned *before* the ETA is quoted (like real
  food-delivery apps), so the model receives all rider features — real
  rider→restaurant distance, live workload, vehicle, experience — at
  checkout AND on re-assignment. If no partner is available at checkout,
  the ETA falls back to a defaults-based estimate.
- Artifacts: `delivery_time_model.pkl` + `model_features.pkl` (project root)

---

## Technology Stack

| Layer      | Technology                                        |
|------------|---------------------------------------------------|
| Backend    | Python 3.12, Flask                                |
| Database   | SQL Server Express (pyodbc), SQLite fallback      |
| Big Data   | MongoDB (263k+ GPS tracking points, optional)     |
| Machine Learning | scikit-learn, pandas, joblib                |
| Frontend   | Bootstrap 5, Chart.js, Leaflet / OpenStreetMap    |
| Data Pipeline | raw → cleaned → SQL Server / MongoDB / ML      |

---

## Quick Start

```text
1) Install Python 3.12 and SQL Server Express (instance .\SQLEXPRESS,
   with "ODBC Driver 17 for SQL Server" installed). MongoDB is optional.

2) pip install -r requirements.txt

3) python scripts/bootstrap_sql_server.py
   (creates the database food_delivery_sys, builds the schema,
    and seeds Karachi demo data)

4) python run.py
   (open http://127.0.0.1:5000)
```

Optional scripts:

```text
python scripts/ingest_sql_server.py   # load historical warehouse data
python scripts/ingest_mongodb.py      # load GPS tracking data into MongoDB
python scripts/train_model.py         # retrain the ML model (optional)
```

---

## Demo Logins

All seeded accounts use the password **`Password@123`**.

| Role             | Usernames                          |
|------------------|------------------------------------|
| Admin            | `admin`                            |
| Customer         | `hamza`, `ayesha`, `bilal`         |
| Delivery Partner | `partner1`, `partner2`, `partner3` |

New delivery partners can also sign up from the Register page
(role: Delivery Partner, staff code required).

---

## SRS Module Mapping

| SRS  | Module                      | Where It Is Implemented                                        |
|------|-----------------------------|----------------------------------------------------------------|
| 3.1  | Auth & Authorization        | `app/auth.py`, role-based guards, password hashing             |
| 3.2  | Customer Profile            | `/customer/profile`                                            |
| 3.3  | Restaurant Management       | `/admin/restaurants` + full menu CRUD                          |
| 3.4  | Order Management            | `app/blueprints/customer.py` (cart, checkout, statuses)        |
| 3.5  | Delivery Partner Management | `app/blueprints/delivery.py`, `/admin/partners`                |
| 3.6  | Real-Time Location Tracking | `app/services/tracking.py` + Leaflet live map                  |
| 3.7  | Route Optimization          | `app/services/routing.py`, `/admin/optimizer`                  |
| 3.8  | Order Assignment            | `app/services/assignment.py` (auto + manual + Assign All)      |
| 3.9  | Analytics & Reporting       | `app/services/analytics.py`, `/admin/analytics`, CSV export    |
| 3.10 | Data Processing & Validation| `app/services/data_pipeline.py`, `/admin/data`                 |
| 3.11 | Ingestion & Storage         | `database/tsql_schema.sql`, `scripts/ingest_*.py`              |
| 3.12 | Dashboards                  | Customer, partner, and admin dashboards with ML ETA            |
| 3.13 | Admin Control Panel         | `/admin/*`, system settings, audit trail                       |
| 3.14 | Alerts & Notifications      | Notification bell + `Notifications` model                      |
| 3.15 | Feedback & Ratings          | Post-delivery ratings with auto-updated averages               |

---

## Testing

Two automated test suites are included:

```text
python scripts/regression.py      # 49 checks across all pages and flows
python scripts/regression_e2e.py  # full end-to-end: order → assign → deliver
```

Both suites pass with **zero failures**.

---

## Data Backup

`scripts/backup_database.py` creates a verified full backup of the SQL Server
database and keeps the newest files in `backups/`.

```text
python scripts/backup_database.py             # backup now
python scripts/backup_database.py --verify    # list kept backups
```

---

## Assumptions

- **Routing distance (SRS 3.7):** route optimization uses **straight-line
  (haversine) distance** between points. Road-following distances from a maps
  API are not integrated; the traffic impact comes from the hour-wise traffic
  profile (derived from the ingested `traffic_data` dataset) combined with the
  admin-configured traffic factor and average speed.
- **GPS (SRS 3.6):** no live GPS device is integrated. The partner dashboard
  simulates movement along the route and stores pings in the `location_logs`
  table, mirrored to MongoDB when reachable.
- **Analytics-only collections (SRS 3.11):** the ingested MongoDB collections
  `tracking_events` and `traffic_data` are historical analytics datasets —
  the live app reads the hour-wise traffic pattern derived from them but does
  not write to them.
- **ETA defaults:** when a value is unknown at prediction time (e.g. before a
  rider is assigned), the ML model uses sensible defaults — bike ride,
  ~3 km pickup leg, median 17-minute prep time, zero active orders
  (see `ml/predictor.py`).
- **Data deliverables:** all files in `data/` are generated deliverables and
  are read as-is — the web app never rewrites them. The cleaning step
  (raw → cleaned) is reproducible via `scripts/clean_data.py`.
- **Workload rule:** only orders accepted in the last 24 hours count towards
  a partner's workload; older historical orders remain in the data for
  analytics only.

---

## Project Structure

```text
run.py                      Flask entry point
config.py                   App and database configuration
app/                        Flask package (blueprints, models, services, templates, static)
ml/predictor.py             Loads the ML model and predicts delivery time
database/tsql_schema.sql    Reference T-SQL warehouse schema
scripts/                    Setup, ingestion, training, backup, and test scripts
data/                       Deliverable datasets (raw / cleaned / sql_server / mongodb / ml)
delivery_time_model.pkl     Trained ML model (R² 0.921 test = production)
model_features.pkl          Feature list used by the model
docs/                       Demo video and prototypes
```

---

## Troubleshooting

- **ODBC driver missing** → install "ODBC Driver 17 for SQL Server".
- **SQL Server not connecting** → check that the SQLEXPRESS service is running
  (`services.msc` → SQL Server (SQLEXPRESS)). The project uses `.\SQLEXPRESS`.
- **MongoDB timeout** → MongoDB is optional; start `mongod` or simply ignore.
- **Want SQLite instead** → set `USE_MSSQL=False` in `.env`.
- **Seeding issues** → rerun `python scripts/bootstrap_sql_server.py`
  (it is idempotent, so it is safe to run again).
- **Port 5000 busy** → change the port in `run.py`.
