# Food Delivery Optimization System — MOON Light 🌙

Aptech eProject — an end-to-end, **Pakistan (Karachi)**-localized food delivery
platform: ML delivery-time prediction, batch route optimization
(pickup-before-drop nearest-neighbour routing with traffic weights),
workload-aware automatic partner assignment, live (simulated) GPS tracking on
maps, analytics dashboards, admin audit trail and a data-pipeline quality page.

**Stack:** Python 3.12 · Flask · SQL Server Express (T-SQL via `pyodbc`) with a
SQLite fallback · MongoDB (optional tracking mirror) · scikit-learn
(HistGradientBoosting delivery-time model, retrained by `scripts/train_model.py`
on `data/ml/delivery_time_dataset.csv` — test **R² 0.936, MAE ~3.4 min,
~96% ETAs within ±10 min**; the pre-retrain pickles are kept as `*.bak`) ·
Chart.js · Leaflet/OpenStreetMap · Bootstrap 5.

---

## 1. Quick start

```text
1)  Install Python 3.12 + SQL Server Express (service: Mssql\$SQLEXPRESS running,
    'ODBC Driver 17 for SQL Server' installed). MongoDB optional.
2)  pip install -r requirements.txt
3)  python scripts/bootstrap_sql_server.py    # creates the live DB food_delivery_sys,
                                              # creates schema, seeds Karachi demo data
4)  python run.py                             # http://127.0.0.1:5000
```

Optional extras:

```text
python scripts/ingest_sql_server.py           # loads the historical WAREHOUSE db
                                              # 'food_delivery' from data/sql_server/*.csv
python scripts/ingest_mongodb.py              # loads mongo tracking collections
                                              # (mongod must be running)
python scripts/train_model.py                 # optional model retrain (writes the pkl files)
```

- Data mode is switchable in `.env`: `USE_MSSQL=True` (default, SQL Server) or
  `False` (plain SQLite file in `instance/`). Connection strings:
  `MSSQL_CONN_STR`, `MSSQL_MASTER_CONN_STR`, `MSSQL_DATABASE=food_delivery_sys`.
- MongoDB mirror: set nothing and it stays optional; the app mirrors GPS pings
  to `mongodb://localhost:27017` DB `moonlight_tracking` when reachable.
- The ML artifacts `delivery_time_model.pkl` / `model_features.pkl` at the
  project root are **never** modified by the web app; they are loaded by
  `ml/predictor.py` through `app/services/ml_bridge.py` for every ETA.

## 2. Demo logins

Every seeded account uses password **`Password@123`**.

| Role             | Usernames                                    |
|------------------|----------------------------------------------|
| Admin            | `admin`                                      |
| Customer         | `hamza`, `ayesha`, `bilal`                   |
| Delivery Partner | `partner1`, `partner2`, `partner3`           |

Seeded content: 6 real Karachi kitchens (Karachi Grill House — Saddar,
Bahadurabad Biryani House, Clifton Seafood Co., Gulshan Green Bowl, PECHS Wood
Fire Pizza, Burns Road Chaat & Haleem) with PKR menus, 30 sample orders,
feedback and partner fleet. All prices render as **Rs** (PKR), payments are
COD / Easypaisa / Card, phones are `+92 …`, addresses use Karachi areas and
Sindh / 75xxx postal codes.

Recommended demo path (video script):

1. `admin` → Dashboard (charts) → **Assignment → Auto-assign** → **Route
   optimizer** (batch orders → optimized map route) → **Data pipeline** →
   **Audit trail** → Settings.
2. New browser: `hamza` → browse restaurants → place order (ML ETA shown) →
   live **tracking** map.
3. Admin assigns the order → customer tracking page shows the partner route.
4. `partner1` → Mark prepared → Dispatch → GPS pings advance → Mark delivered.
5. Customer gets notifications → rates the order (5★) → analytics update.

## 3. SRS module mapping (15 functional modules)

| SRS  | Module                       | Implementation                                                                  |
|------|------------------------------|---------------------------------------------------------------------------------|
| 3.1  | Auth & Authorization         | `app/auth.py`, `app/blueprints/auth.py` (pbkdf2 hashes, session timeout, role guards) |
| 3.2  | Customer profile             | `/customer/profile` (Karachi address, preferences, order history)                |
| 3.3  | Restaurant management        | `/admin/restaurants` + menu CRUD (hours, availability, cuisine)                   |
| 3.4  | Order management             | `app/blueprints/customer.py` (cart, checkout, cancel, statuses)                   |
| 3.5  | Delivery partner management  | `app/blueprints/delivery.py`, `/admin/partners`, availability + status history    |
| 3.6  | Real-time location tracking  | `app/services/tracking.py` (Mongo `location_logs` mirror + LocationLog) + Leaflet |
| 3.7  | Route optimization           | `app/services/routing.py` + `/admin/optimizer` (batch pickups/drops, traffic ETA) |
| 3.8  | Order assignment             | `app/services/assignment.py` (distance + workload + ML score hook, auto/manual)   |
| 3.9  | Analytics & reporting        | `app/services/analytics.py`, `/admin/analytics` (Chart.js charts, CSV exports)    |
| 3.10 | Data processing/validation   | `app/services/data_pipeline.py`, `/admin/data` (quality report + issue flags)     |
| 3.11 | Ingestion & storage          | `database/tsql_schema.sql` (warehouse) + app schema via `db.create_all()`, `scripts/ingest_*.py`, `scripts/bootstrap_sql_server.py` |
| 3.12 | Dashboards                   | customer, partner and admin dashboards incl. ETA prediction (ML model)            |
| 3.13 | Admin control panel          | `/admin/*` + `system_settings` optimization parameters + `/admin/audit` trail     |
| 3.14 | Alerts & notifications       | `Notifications` model + notification bell (`/api/*`)                              |
| 3.15 | Feedback & ratings           | post-delivery ratings, restaurant/partner averages auto-update                    |

Non-functional: password hashing + login lockout (security), session
auto-logout, bulk ingestion of 360k+ documents (scalability), append-only audit
trail, PKR/Karachi localization throughout.

## 4. Assumptions (per SRS ReadMe requirement)

* **GPS:** no live GPS API is integrated; the partner dashboard simulates
  movement along the optimized route and stores pings in SQL Server
  (`location_logs` table) and mirrors them to MongoDB when reachable.
* **Traffic:** route/ETA weights come from admin-configured traffic factor +
  city avg speed (Settings page); the historical Mongo `traffic_data` snapshot
  remains part of the ingested dataset.
* **ETA before assignment:** the ML model gets sensible defaults (Bike ride,
  ~3 km pickup leg, median prep time, workload 0) — see `ml/predictor.py`.
* **Historical orders** in the seeded data remain for analytics; only orders
  accepted in the last 24 h count towards a partner's workload.
* All `data/` files are generated deliverables and are loaded/read verbatim —
  the web app never rewrites them.

### 4.1 Data backups (SRS "Reliability: Data Backup")

`scripts/backup_database.py` performs a checksum-verified full `BACKUP
DATABASE` of the SQL Server app database (`food_delivery_sys`) and keeps the
newest N files in `backups/` (default 24 counts, one per scheduled run):

```powershell
python scripts/backup_database.py            # backup now
python scripts/backup_database.py --verify   # list kept backups
python scripts/backup_database.py --keep 168 # hourly rotation for a week
# hourly Task Scheduler example:
schtasks /Create /TN "MOONLight-DB-Backup" /SC HOURLY /TR ^
  "python C:\path\to\scripts\backup_database.py --keep 168"
```

First run grants the SQL Server service account write access on the
`backups/` folder so the `.bak` lands directly in the project. The Sqlite
fallback mode uses the online `sqlite3` backup API instead.

## 5. Project structure

```text
run.py                      Flask entry point (runs create_app())
config.py                   DB connections, app + settings knobs
app/                        Flask package (blueprints, models, services, templates, static)
  extensions.py             mini-ORM with SQL Server (pyodbc) + SQLite backends
  models.py                 entities incl. AuditLog
  seed.py                   Karachi demo data
  services/                 routing, assignment, tracking, ml_bridge, audit, data_pipeline...
  blueprints/               main, auth, customer, delivery, admin, api
ml/predictor.py             loads the untouched pkl files, predict_eta(features)
database/tsql_schema.sql    reference T-SQL schema of the data warehouse (SSMS)
scripts/                    bootstrap_sql_server, ingest_sql_server,
                            ingest_mongodb, train_model
data/                       deliverable dataset (raw / cleaned / sql_server / mongodb / ml)
delivery_time_model.pkl     trained HistGradientBoosting model (R2 0.936)
delivery_time_model.pkl.bak previous model artifacts kept as safety copies
model_features.pkl          encoded feature-column list consumed by ml/predictor.py
docs/                       demo video and prototypes
```

## 6. Troubleshooting

* `ODBC Driver 17 for SQL Server` missing → install the Microsoft ODBC driver.
* Named-pipes / login errors on `localhost` → this project targets the named
  instance `.\SQLEXPRESS`; check the SQL Server **Express** service is running
  (`services.msc` → SQL Server (SQLEXPRESS)).
* `ServerSelectionTimeoutError` → MongoDB is optional; start `mongod` or ignore.
* Force the SQLite fallback → set `USE_MSSQL=False` in `.env`.
* Ingest identity/seed errors → rerun `python scripts/bootstrap_sql_server.py`
  (schema creation and seeding are idempotent); the warehouse ingest script
  drops + recreates its schema safely.
* Port 5000 busy → edit `run.py` (`app.run(port=...)`).
