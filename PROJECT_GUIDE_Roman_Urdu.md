# 🌙 MOON Light — Food Delivery Optimization System

> **Complete Guide (Roman Urdu mein)** — Project kya hai, kaise chalate hain, kaise use karte hain.
> English README technical detail ke liye: [`README.md`](README.md)

---

## 📌 Project ek line mein

Karachi (Pakistan) ki localization ke sath **Food Delivery web application** — jisme customer order karta hai,
admin best delivery partner assign karta hai (ML optimizer se), aur live tracking hoti hai.
Delivery time ka **andaza Machine Learning model** lagata hai (accuracy **94% / R² 0.936**).

---

## 🛠️ Technologies

| Hisa | Technology |
|---|---|
| Backend | Python **Flask** (templates ke liye Jinja2) |
| Database | **SQL Server** (`.\SQLEXPRESS`, DB: `food_delivery_sys`) + SQLite fallback |
| ML Model | scikit-learn **HistGradientBoostingRegressor** |
| Frontend | HTML + **Bootstrap** + custom CSS/JS (navy-gold theme) |
| Data Warehouse | `data/` folder (raw → cleaned → sql_server → mongodb → ml) |

---

## 🚀 Project kaise chalate hain (Step by Step)

### Step 1: Requirements (ek dafa)
```powershell
pip install -r requirements.txt
```
- SQL Server Express installed ho + ODBC Driver 17
- Python 3.12+

### Step 2: Database setup (ek dafa)
```powershell
python scripts\bootstrap_sql_server.py
```
Ye khud DB banata hai + tables + demo data (agar pehle se hai to skip).

### Step 3: Server start karo
```powershell
python run.py
```
Browser mein kholo: **http://127.0.0.1:5000**

---

## 🔑 Demo Logins (sab ka password: `Password@123`)

| Role | Username | Kya kar sakta hai |
|---|---|---|
| Admin | `admin` | Poora control: orders, partners, users, analytics, optimizer |
| Customer | `hamza`, `ayesha`, `bilal` | Order karna, cart, tracking, feedback |
| Delivery Partner | `partner1`, `partner2`, `partner3` | Assignments, route, status update |

**Naya account bhi bana sakte ho** — Register page se (bug fix ho chuka, dashboard seedha khulta hai ✅)

---

## 👨‍💼 Admin kaise use kare

1. `admin` / `Password@123` se login
2. **Dashboard** — live numbers (orders, revenue, partners)
3. **Optimizer** ⭐ — project ka HERO page:
   - Unassigned orders dikhte hain
   - "Auto-assign" dabao → system **best partner** chunta hai
   - Logic: distance (kam) + workload (kam) + ML ETA (kam) + partner rating
   - Har partner ka score + wajah dikhti hai ("at capacity 3/3" waghera)
4. **Orders** — kisi bhi order pe detail kholo:
   - Partner assign/reassign
   - Status aage barhao: `confirmed → prepared → dispatched → delivered`
5. **Analytics** — charts (orders per day, revenue, on-time %)
6. **Settings** — delivery fee (base Rs + per-km), partner ka max load
7. **Data** — data pipeline refresh (admin panel se)
8. **Reports** — CSV export (orders.csv, partners.csv)
9. **Audit** — kis admin ne kya kiya, sab record

## 🛒 Customer kaise use kare

1. Register (naya account) ya `hamza` login
2. **Restaurants** browse karo → koi kholo → items **cart** mein dalo
3. **Checkout** — address confirm + payment mode: **COD / Easypaisa / Card**
4. Order place! → turant **ETA** milega (ML model se, source: ml)
5. **Tracking page** — partner ki live position + status progress bar
6. Deliver hone ke baad **feedback/rating** do (stars)

## 🏍️ Partner kaise use kare

1. `partner1` / `Password@123` login
2. **Dashboard** — kitne orders assigned, earnings
3. **Assignments** — naye orders accept/dekhо
4. **Route** — pickup → delivery ka map route
5. Order ki status update karo (picked up → delivered)

---

## 🧠 ML Model (accuracy ka jawab)

| Cheez | Value |
|---|---|
| Algorithm | HistGradientBoostingRegressor (scikit-learn) |
| Training data | `data/ml/delivery_time_dataset.csv` — 13,314 orders |
| **Accuracy (R²)** | **0.936 (≈94%)** ✅ requirement: 90% |
| MAE | ~3.4 minute |
| ETAs ±10 min ke andar | ~96% |
| Model file | `delivery_time_model.pkl` + `model_features.pkl` (root mein) |

**Retrain karna ho to:**
```powershell
python scripts\train_model.py
```
(Purana model automatically `.bak` mein safe ho jata hai)

---

## ✅ Quality Tests (SRS verification)

```powershell
python scripts\regression.py        # 49 automated checks (saare pages/features)
python scripts\regression_e2e.py    # Poora user journey: register → order → assign → feedback
```
**Aakhri result (11-Nov-2026): FAILURES: 0 / E2E FAILURES: 0** ✅

## 💾 Database Backup

```powershell
python scripts\backup_database.py
```
- `backups/` folder mein `.bak` file banti hai (checksum verified)
- Purani backups auto-rotate hoti hain

---

## 📁 Structure (quick map)

```
run.py                  → START (python run.py)
config.py               → settings (DB, security, ML)
app/
  __init__.py           → app factory (sab jorne wali)
  extensions.py         → DB engine (mini-ORM)
  models.py             → DB tables
  auth.py               → login/CSRF/roles
  blueprints/           → routes: main, auth, customer, delivery, admin, api
  services/             → logic: assignment (optimizer), analytics, tracking, cart...
  templates/            → 40 HTML pages (admin/customer/delivery/auth...)
  static/               → css/style.css + js (tracking, charts) + bootstrap
ml/predictor.py         → ML model load + predict
scripts/                → train_model, backup, regression tests, ingest
data/                   → raw → cleaned → sql_server → mongodb → ml (warehouse)
database/tsql_schema.sql → SQL Server schema
```

---

## 🐛 Troubleshooting (common masle)

| Masla | Hal |
|---|---|
| Server start nahi hota | Check karo port 5000 free hai + Python install |
| DB error (SQL Server) | `.\SQLEXPRESS` service chalu karo (services.msc → SQL Server (SQLEXPRESS)) |
| ML model load nahi | `delivery_time_model.pkl` root mein hona chahiye — `python scripts\train_model.py` chalao |
| DB fresh chahiye | `python scripts\bootstrap_sql_server.py` (phir `flask seed-demo`) |
| Backup nahi banta | `scripts\backup_database.py` folder permissions check karo |

---

## 📋 SRS Compliance (15 modules — sab maujood ✅)

Auth & roles ✅ | Restaurant/menu browse ✅ | Cart & checkout ✅ | Order management ✅ |
Partner assignment (ML optimizer) ✅ | Live tracking ✅ | Notifications ✅ |
Ratings/feedback ✅ | Admin panel ✅ | Analytics & reports ✅ |
Data pipeline ✅ | Settings ✅ | Audit log ✅ | Backups ✅ | ML ETA prediction ✅

**Pakistan localization:** Rs/PKR, Karachi areas, +92 phones, COD/Easypaisa/Card ✅

---

## 🗓️ Version History

- **30-Oct-2026:** Original build (purana ML model ~75%)
- **04-Nov-2026:** UI restyle (navy/gold MOON Light) + ML retrain **R² 0.936**
- **05-Nov-2026:** Signup bug fix (fresh user dashboard 500 error) — poora flow clean
- **11-Nov-2026:** Full SRS re-audit — 0 failures, 0 errors, sab healthy

---

*© 2026 MOON Light — Built with Flask. Dine under the moonlight 🌙*
