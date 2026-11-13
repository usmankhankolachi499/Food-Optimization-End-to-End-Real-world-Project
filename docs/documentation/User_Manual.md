# User Manual — Food Delivery Optimization System (MOON Light)

How to use the platform for each role. All demo accounts use the
password **`Password@123`**.

---

## 1. Getting Started

1. Run the app: `python run.py` → open `http://127.0.0.1:5000`
2. Register a new account from the **Register** page, or use a demo login.
3. Registering as **Admin** or **Delivery Partner** requires the staff code
   (demo code: `MOON-STAFF-2026` — change it in `.env`).

| Role | Demo usernames |
|---|---|
| Admin | `admin` |
| Customer | `hamza`, `ayesha`, `bilal` |
| Delivery Partner | `partner1`, `partner2`, `partner3` |

---

## 2. Customer Guide

### Browse and Order
1. Home page shows a search box and featured restaurants (12 Karachi kitchens).
2. Open any restaurant → browse the menu by category.
3. Click **Add to cart** on the dishes you want.
4. Open the cart → adjust quantity or remove items → **Checkout**.
5. At checkout, fill in:
   - Delivery address (or pick your location on the map)
   - Payment method: **COD / Easypaisa / Card**
6. The system shows the **predicted delivery time** (Machine Learning).
7. Place the order — you get a confirmation notification.

> Note: you cannot order from a restaurant that is currently closed.

### Track Your Order
- Open **My Orders** → click an order → the tracking page shows:
  - Live status: confirmed → prepared → dispatched → delivered
  - The rider moving on a real map (once dispatched)

### After Delivery
- Rate the order (1–5 stars) and leave a comment.
- Feedback updates the restaurant's and rider's average ratings.

### Profile
- Update your address, phone, and map location under **Profile**.
- Change your password any time.

---

## 3. Delivery Partner (Rider) Guide

1. Log in → the **Dashboard** shows your earnings (Rs), active orders,
   and today's summary.
2. **Assignments** page shows new delivery requests — **Accept** the ones
   you can deliver.
3. Open an active order to:
   - Update your **location** (used for live tracking)
   - Move the status: prepared → dispatched → delivered
   - See the optimized route on the map
4. Use the availability toggle (Available / Off-duty) on your dashboard.
5. **History** page lists all your past deliveries with ratings.

---

## 4. Admin Guide

### Dashboard
- Live statistics: orders today, revenue, active riders, live order feed.

### Orders
- Search and filter orders (status, assignment).
- Open any order to assign / reassign a rider, or change status.
- **Assign All** button: assigns every pending order in one click —
  and hires new riders automatically if the fleet is short.
- Download a CSV report of the last 30 days.

### Optimizer
- Shows unassigned orders and ranked riders for each one
  (score based on distance, workload, and rating).
- Batch mode: pick several orders → get an optimized multi-stop route
  on the map.

### Restaurants & Menu
- Add / edit / deactivate restaurants, set opening and closing times.
- Manage menu items: price, prep time, availability toggle.

### Analytics & Reports
- Charts: orders per day, revenue, top restaurants, on-time percentage.
- CSV exports for orders and partners.

### Settings (automation)
- Auto-assign orders on placement
- Live order simulation (2 demo orders/minute) and its rate
- Auto-hire partners when order volume grows
- Delivery fee (base + per km), average speed, traffic factor

### Users, Partners & Audit
- Create / edit / deactivate accounts of any role.
- Rider profiles: vehicle, availability, performance.
- Audit trail records every admin action.

### Data Pipeline
- The Data page shows dataset quality: row counts, issues found,
  ingestion status for SQL Server and MongoDB.
- Re-run steps from the command line:
  - `python scripts/clean_data.py` (raw → cleaned)
  - `python scripts/ingest_sql_server.py` (historical warehouse)
  - `python scripts/ingest_mongodb.py` (GPS tracking data)

---

## 5. Common Questions

**Estimated time seems wrong?**
It is predicted from real historical data (94% accuracy). Traffic and the
rider's workload can still change the real time slightly.

**The rider is not moving on the map?**
Location updates arrive when the rider updates their position (or when the
demo simulator advances the order). Refresh the tracking page.

**Someone signed up as Admin by mistake?**
Admins can deactivate any account from the Users page.
