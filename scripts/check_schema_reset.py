"""Idempotent schema test: drop_all (with FK constraints) then create_all +
re-seed; verifies the SQL Server backend round-trips cleanly."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import AuditLog, Order, Restaurant, User

application = create_app()
with application.app_context():
    print("before: users", User.query.count(), "orders", Order.query.count())
    db.drop_all()
    print("drop_all OK")
    db.create_all()
    print("create_all OK")
    from app.seed import seed_demo

    print(seed_demo(with_orders=True))
    print("after: users", User.query.count(), "restaurants", Restaurant.query.count(),
          "orders", Order.query.count(), "audit", AuditLog.query.count())
    # FK sanity: restaurant delete cascade-free path (has orders -> blocked path handled in UI)
    active = Order.query.filter(Order.status.in_(["placed", "confirmed", "prepared", "dispatched"])).count()
    print("active orders:", active)
