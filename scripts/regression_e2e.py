"""Full E2E order lifecycle (regression): place -> assign -> dispatch ->
deliver -> rate, plus ML ETA source verification."""
import os
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:5000"
PW = "Password@123"
fails = []


def csrf(s, url="/"):
    r = s.get(BASE + url, timeout=30)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return m.group(1) if m else None


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL "), label, extra)
    if not cond:
        fails.append(label)


# ----- customer places order ------------------------------------------------
c = requests.Session()
c.post(BASE + "/auth/login", data={"identifier": "bilal", "password": PW, "csrf_token": csrf(c, "/auth/login")}, timeout=30)
r = c.get(BASE + "/customer/dashboard", timeout=30)
check("bilal logged in", "Bilal" in r.text)

r = c.get(BASE + "/restaurants", timeout=30)
rid = re.search(r'/restaurants/(\d+)', r.text).group(1)
r = c.get(BASE + f"/restaurants/{rid}", timeout=30)
item_id = re.search(r'/customer/cart/add/(\d+)', r.text).group(1)
r = c.post(BASE + f"/customer/cart/add/{item_id}", data={"csrf_token": csrf(c), "quantity": "2"}, timeout=30)
check("item added to cart", r.status_code == 200)
r = c.get(BASE + "/customer/cart", timeout=30)
check("cart has item", "Remove" in r.text or "remove" in r.text.lower())
r = c.get(BASE + "/customer/checkout", timeout=30)
check("checkout page", r.status_code == 200 and "Easypaisa" in r.text)
token = csrf(c, "/customer/checkout")
r = c.post(BASE + "/customer/checkout", data={
    "csrf_token": token,
    "payment_method": "Easypaisa",
    "delivery_address": "House 44, Block 13-D, Gulshan-e-Iqbal, Karachi",
}, timeout=60)
placed = r.status_code in (200, 302)
check("order placed", placed, r.url[-50:])
order_id = None
if placed:
    page = r.text
    if r.status_code == 302:
        page = c.get(r.url, timeout=30).text
    m = re.search(r'/customer/orders/(\d+)', page) or re.search(r'/customer/orders/(\d+)', c.get(BASE + "/customer/orders", timeout=30).text)
    order_id = m.group(1) if m else None
check("order id found", bool(order_id), order_id)

if order_id:
    r = c.get(BASE + f"/customer/orders/{order_id}", timeout=30)
    check("order detail", r.status_code == 200)
    check("ETA minutes shown", bool(re.search(r'\d{1,3}\s*min', r.text)))

    # ----- admin assigns ----------------------------------------------------
a = requests.Session()
a.post(BASE + "/auth/login", data={"identifier": "admin", "password": PW, "csrf_token": csrf(a, "/auth/login")}, timeout=30)
if order_id:
    r = a.get(BASE + f"/admin/orders/{order_id}", timeout=30)
    check("admin open order", r.status_code == 200)
    m = re.search(r'name="partner_id"[\s\S]{0,600}?value="(\d+)"', r.text)
    partner_id = m.group(1) if m else None
    check("partner ranked in order page", bool(partner_id), partner_id)
    r = a.post(BASE + f"/admin/orders/{order_id}/assign", data={
        "csrf_token": csrf(a, f"/admin/orders/{order_id}"), "partner_id": partner_id,
    }, timeout=60)
    check("order assigned", r.status_code in (200, 302))
    r = a.get(BASE + "/admin/audit", timeout=30)
    check("audit order_assigned", "Order Assigned" in r.text)

    # ----- stage through statuses ------------------------------------------
    for status in ("prepared", "dispatched", "delivered"):
        r = a.post(BASE + f"/admin/orders/{order_id}/status", data={
            "csrf_token": csrf(a, f"/admin/orders/{order_id}"), "status": status,
        }, timeout=60)
        check(f"admin marks {status}", r.status_code in (200, 302))

    # ----- customer rates ---------------------------------------------------
    r = c.get(BASE + f"/customer/orders/{order_id}/feedback", timeout=30)
    check("feedback form", r.status_code == 200)
    r = c.post(BASE + f"/customer/orders/{order_id}/feedback", data={
        "csrf_token": csrf(c, f"/customer/orders/{order_id}/feedback"),
        "restaurant_rating": "5", "partner_rating": "5",
        "comment": "Zabardast! MOON Light fast delivery in Karachi.",
    }, timeout=60)
    check("feedback submitted", r.status_code in (200, 302))

# ----- ML source check ------------------------------------------------------
from app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from app.services.ml_bridge import ml_available, predict_eta

    check("ml_available", ml_available())
    res = predict_eta(distance_km=4.0, prep_time_min=17, item_count=2)
    check("ML ETA source", res.get("source") == "ml", str(res))

print("\n==== E2E FAILURES:", len(fails), fails)
sys.exit(1 if fails else 0)
