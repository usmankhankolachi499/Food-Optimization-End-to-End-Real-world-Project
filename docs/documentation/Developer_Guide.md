# Developer Guide — Food Delivery Optimization System (MOON Light)

Everything a developer needs to understand, run, and extend the project.

---

## 1. Architecture

```
run.py                     Flask entry point
config.py                  configuration (env-driven)
app/
  extensions.py            mini-ORM (pyodbc -> SQL Server, SQLite fallback)
  models.py                12 entities (User, Order, Restaurant, ...)
  seed.py                  idempotent Karachi demo data
  auth.py                  login, roles, session, password hashing
  blueprints/              main, auth, customer, delivery, admin, api
  services/                routing, assignment, tracking, ml_bridge,
                           audit, analytics, data_pipeline, settings,
                           simulator
  templates/ + static/     Jinja2 + Bootstrap 5 + Leaflet + Chart.js
ml/predictor.py            ML layer (loads the pkl model)
scripts/                   setup, cleaning, ingestion, training, tests
data/                      deliverable datasets (raw/cleaned/sql_server/mongodb/ml)
database/tsql_schema.sql   warehouse schema (SSMS)
```

**Key design points**

- A small custom ORM layer (`extensions.py`) talks to SQL Server through
  pyodbc. No SQLAlchemy dependency — the same models fall back to SQLite
  when SQL Server is not available (`USE_MSSQL=False`).
- All configuration is environment-driven (`.env`); nothing sensitive is
  hardcoded (SECRET_KEY is auto-generated to `instance/secret_key.txt` on
  first run if not provided).
- The ML artifacts (`delivery_time_model.pkl`, `model_features.pkl`) are
  **read-only** for the web app — only `scripts/train_model.py` writes them.

## 2. Setup

```text
1) Python 3.12 + SQL Server Express (.\SQLEXPRESS) + ODBC Driver 17
2) pip install -r requirements.txt
3) python scripts/bootstrap_sql_server.py   # create DB, schema, seed data
4) python run.py                            # http://127.0.0.1:5000
```

Optional: `ingest_sql_server.py`, `ingest_mongodb.py`, `clean_data.py`,
`train_model.py`, `backup_database.py`.

Environment switches (see `.env.example`): `USE_MSSQL`, `MSSQL_CONN_STR`,
`MONGO_URI`, `ML_ENABLED`, `STAFF_SIGNUP_CODE`, `SIMULATE_ORDERS=0`
(disables the simulator thread — useful for running test scripts).

## 3. Machine Learning Pipeline

**Training (offline, once):**

```
data/ml/delivery_time_dataset.csv   13,314 records
        │  scripts/train_model.py
        │  - one-hot encoding (pd.get_dummies) → 28 columns
        │  - train_test_split (80/20, random_state=42)
        │  - candidates: GradientBoostingRegressor (old baseline),
        │               HistGradientBoostingRegressor (tuned)
        │  - robustness check on 4 extra splits (seeds 7, 123, 2026)
        ▼
delivery_time_model.pkl   HistGradientBoostingRegressor
                          (max_iter=600, lr=0.045, max_leaf_nodes=31,
                           l2=0.05, early_stopping=True)
model_features.pkl        exact 28-column list
        Test metrics: R² 0.921 · MAE 3.68 min · ~94% within ±10 min
        (train = serve consistent: traffic hour-probability table)
```

**Prediction (online, per order — full features at both stages):**

```
Step 1 - checkout:
customer.py checkout
  → auto_assign_order(order)              # rider pehle assign hota hai
  → routing.estimate_eta(order,
        partner_profile=profile)          # saare features REAL:
                                          # distance, prep, hour, traffic,
                                          # p2r (haversine), workload, vehicle...
  → ml_bridge.predict_eta(...)            # bridge: try ML, fallback heuristic
  → ml/predictor.predict_eta(features)    # builds 28-col row (one-hot like training)
  → model.predict() → minutes             # read-only pkl, cached per process

Step 2 - re-assignment (assign_order() bhi same path):
  → routing.estimate_eta(order, partner_profile=profile)

Fallback: koi rider available na ho to ETA defaults-based estimate hoti
hai, aur assignment ke baad full-feature ETA lag jati hai.
```

- The bridge always returns `{"minutes": int, "source": "ml"|"heuristic"}`
  so the UI can show the prediction source.
- Accuracy, honestly stated (one number everywhere): the model is
  **train/serve consistent** — traffic is estimated from the same
  hour-probability table (`ml.predictor.TRAFFIC_PROBS_BY_HOUR`) during
  training and serving, so the test R² **0.921** IS the production
  accuracy. No skew by design. The oracle upper bound (with recorded
  real traffic, unavailable at serving) is R² 0.937 — that equals the
  dataset's noise floor (5-fold OOF), which is why ~0.92 is the maximum
  honest live number. `scripts/eval_production_accuracy.py` prints both.
- If the model files are missing or fail to load, the deterministic
  heuristic (`prep + distance/speed × traffic`) keeps the app working.

**Retraining:** `python scripts/train_model.py` — writes new pkl files;
old artifacts were kept as `*.bak` during migration and can be recreated
by re-running the script with the old dataset.

## 4. Assignment Engine (`app/services/assignment.py`)

Deterministic scoring — **not** the ML model:

```
score(rider) = distance_to_pickup + workload × 2   (lower = better)
```

- `ranked_partners(order)` lists eligible riders (capacity, availability).
- `assign_order(order, partner, force=...)` performs and audits the change.
- `auto_assign_order()` picks the best rider automatically.
- `simulator.hire_if_needed()` hires new riders when
  `unassigned_orders > fleet_capacity + 2` (fleet cap: 14, max 3/tick).
- `POST /admin/orders/assign-all` assigns everything pending in one click,
  hiring riders if needed.

## 5. Live Simulator (`app/services/simulator.py`)

- Daemon thread started in `create_app()`; disabled by `SIMULATE_ORDERS=0`.
- Places `sim_orders_per_minute` (default 2) orders per minute, tagged
  `SIM:` in `notes` so real orders are never touched.
- Advances the lifecycle (confirmed → prepared → dispatched → delivered)
  and force-assigns orders that wait too long.
- Cleans up delivered SIM orders older than 3 days (active cap 40).
- Uses `app.test_request_context("/")` internally because notifications
  build URLs with `url_for`.

## 6. Database

12 tables: `users`, `customer_profiles`, `delivery_partner_profiles`,
`restaurants`, `menu_items`, `orders`, `order_items`, `notifications`,
`feedback`, `admin_audit_log`, `location_logs`, `system_settings`.
Full relationships: see `docs/documentation/ER_Diagram.md`.

Notes for the mini-ORM:

- Booleans must be bound as `1`/`0` (SQL Server rejects `False` literals).
- Identity inserts use `OUTPUT INSERTED."id"`.
- `LIKE '[...'` is a character class in SQL Server — avoid leading brackets
  in patterns (this is why SIM orders are tagged `SIM:` instead of `[SIM]`).

## 7. Testing

```text
python scripts/regression.py       # 49 checks: pages, auth, roles, flows
python scripts/regression_e2e.py   # end-to-end: order → assign → deliver
```

Both suites require the live server on `127.0.0.1:5000` and set
`SIMULATE_ORDERS=0` internally to avoid simulator interference.

## 8. Conventions

- Python 3.12, short student-style comments, no heavy dependencies.
- All money in PKR rendered as `Rs`; phone numbers `+92 …`; Karachi areas.
- Templates extend `base.html`; shared macros live in
  `templates/partials/macros.html`.
- Audit every admin mutation via `app/services/audit.log_action`.
- Settings read through `app/services/settings.py` (`get_bool`, `get_int`,
  `get_float`) so admin changes apply without restart.
