"""
SQL Server setup (SRS 3.11).

  python scripts/bootstrap_sql_server.py          # create DB + tables + seed

food_delivery_sys DB + schema + demo data (Karachi restaurants, partners,
orders) ek hi run mein, phir app seedha SQL Server pe chalti hai.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyodbc  # noqa: E402

from config import Config  # noqa: E402


def create_database() -> str:
    conn = pyodbc.connect(Config.MSSQL_MASTER_CONN_STR, timeout=15, autocommit=True)
    cur = conn.cursor()
    exists = cur.execute(
        "SELECT COUNT(*) FROM sys.databases WHERE name = ?", Config.MSSQL_DATABASE
    ).fetchone()[0]
    if not exists:
        print(f"Creating database {Config.MSSQL_DATABASE} ...")
        cur.execute(f"CREATE DATABASE {Config.MSSQL_DATABASE}")
        print("Database created.")
    else:
        print(f"Database {Config.MSSQL_DATABASE} already exists.")
    conn.close()
    return "created" if not exists else "exists"


def main():
    create_database()
    import app as app_module  # application factory (scripts as root)

    application = app_module.create_app()
    with application.app_context():
        from app.extensions import db

        db.create_all()
        from app.seed import seed_demo

        print(seed_demo(with_orders=True))
        # sanity checks against T-SQL tables
        from app.models import User, Restaurant, Order, Feedback, SystemSetting

        counts = {
            "users": User.query.count(),
            "restaurants": Restaurant.query.count(),
            "orders": Order.query.count(),
            "feedback": Feedback.query.count(),
            "system_settings": SystemSetting.query.count(),
        }
        print("SQL Server row counts:", counts)
        print("Backend check OK.")


if __name__ == "__main__":
    main()
