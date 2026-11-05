"""
SRS 3.11 - Data Ingestion: CSV -> SQL Server and JSONL -> MongoDB.

Usage (one-time setup, run from project root):
    python scripts/ingest_sql_server.py        # schema + bulk load
    python scripts/ingest_mongodb.py           # location logs, traffic, events
    python scripts/ingest_mongodb.py --drop    # re-load from zero

Loads the DATA WAREHOUSE database (``food_delivery``, matching the
data/sql_server/*.csv deliverables). The live application database,
``food_delivery_sys``, is created separately via
scripts/bootstrap_sql_server.py.

Bulk inserts use FastExecutemany (pyodbc) which loads 15k orders in
seconds instead of minutes.
"""
import os
import sys
import re
import pyodbc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

BASE = config.DATA_DIR
SQL_DIR = os.path.join(BASE, "sql_server")
MONGO_DIR = os.path.join(BASE, "mongodb")

WAREHOUSE_DB = os.getenv("WAREHOUSE_DB", "food_delivery")
MASTER_CONN_STR = config.MSSQL_MASTER_CONN_STR

TABLES = ["users", "customers", "restaurants", "menu_items", "delivery_partners",
          "orders", "order_items", "ratings", "notifications",
          "partner_status_history", "admin_audit_log"]


def run_schema(cursor):
    here = os.path.dirname(os.path.abspath(__file__))
    sql = open(os.path.join(here, "..", "database", "tsql_schema.sql"),
               encoding="utf-8").read()
    # "GO" is a client batch separator, not valid T-SQL - send batches
    # separately (line-based so identifiers containing "GO" survive)
    batches = re.split(r"(?im)^\s*GO\s*$", sql)
    for batch in batches:
        if batch.strip():
            cursor.execute(batch)
            cursor.commit()          # DDL is transactional - persist per batch


def load_table(cursor, table):
    import csv
    path = os.path.join(SQL_DIR, f"{table}.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    cols, data = rows[0], rows[1:]
    if table == "users":
        # the generator wrote 'DeliveryPartner' without a space; schema uses
        # 'Delivery Partner' (SRS role label) - normalise on the way in
        idx = cols.index("role")
        data = [r[:idx] + ["Delivery Partner" if r[idx] == "DeliveryPartner" else r[idx]] + r[idx + 1:]
                for r in data]
    if table == "orders":
        # NULLs come through as empty strings; the generator also wrote
        # 441 rows with a 'dispatche' typo - normalise on the way in
        si = cols.index("status")
        data = [[(None if v == "" else ("dispatched" if i == si and v == "dispatche" else v))
                 for i, v in enumerate(r)] for r in data]
    ph = ",".join("?" * len(cols))
    # empty strings -> NULL (all tables), '00:00'-style TIME strings stay as-is
    data = [[(None if v == "" else v) for v in r] for r in data]
    # CSVs carry the original primary keys; allow identity override only on
    # columns that actually have IDENTITY (users/ratings/notifications/audit)
    identity = bool(cursor.execute(
        "SELECT 1 FROM sys.identity_columns i JOIN sys.tables t"
        " ON t.object_id = i.object_id JOIN sys.schemas s ON s.schema_id = t.schema_id"
        " WHERE s.name + '.' + t.name = 'dbo.' + ?", (table,)).fetchone())
    stmt = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})"
    if identity:
        cursor.execute(f"SET IDENTITY_INSERT {table} ON")
        try:
            cursor.executemany(stmt, data)
        finally:
            cursor.execute(f"SET IDENTITY_INSERT {table} OFF")
    else:
        cursor.executemany(stmt, data)
    # keep future identity inserts starting above the loaded keys
    id_col = next((c for c in ("user_id", "customer_id", "rating_id", "notif_id",
                               "log_id", "restaurant_id", "item_id", "order_id",
                               "partner_id") if c in cols), None)
    if identity and id_col and data:
        mx = max(int(r[cols.index(id_col)]) for r in data)
        # reseed AFTER the IDENTITY_INSERT block closed, then verify
        cursor.execute(f"DBCC CHECKIDENT ('{table}', RESEED, {mx})")
        val = cursor.execute(
            "SELECT last_value FROM sys.identity_columns i JOIN sys.tables t"
            " ON t.object_id = i.object_id WHERE t.name = ?", (table,)).fetchone()[0]
        assert int(val) == mx, f"{table}: identity reseed failed ({val} != {mx})"
    print(f"  {table:<24} {len(data):>7,} rows")
    return len(data)


def _exec_bulk(cursor, table, cols, data, ph):  # kept for reuse/debugging
    cursor.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})", data)


def main():
    # 1. create database if missing (connect to master with autocommit,
    #    because CREATE DATABASE cannot run inside a T-SQL transaction)
    master = pyodbc.connect(MASTER_CONN_STR, timeout=10, autocommit=True)
    mcur = master.cursor()
    row = mcur.execute(
        "SELECT COUNT(*) FROM sys.databases WHERE name=?",
        WAREHOUSE_DB).fetchone()
    if not row[0]:
        mcur.execute(f"CREATE DATABASE {WAREHOUSE_DB}")
        print(f"Created database {WAREHOUSE_DB}")
    master.close()

    # 2. schema + bulk load
    conn_str = MASTER_CONN_STR.replace(
        "DATABASE=master", f"DATABASE={WAREHOUSE_DB}")
    conn = pyodbc.connect(conn_str, timeout=10)
    cur = conn.cursor()
    print("Applying T-SQL schema ...")
    run_schema(cur)
    print("Bulk loading CSVs ...")
    total = 0
    for table in TABLES:
        total += load_table(cur, table)
        cur.commit()                 # persist each table as it completes
    print("Applying orders FK ...")
    cur.execute("""
        IF OBJECT_ID('FK_orders_partner','F') IS NULL
           ALTER TABLE orders ADD CONSTRAINT FK_orders_partner
           FOREIGN KEY (partner_id) REFERENCES delivery_partners(partner_id);
    """)

    # 3. default optimization settings (SRS 3.13)
    settings = [("delivery_fee", "150"), ("free_delivery_above", "2000"),
                ("max_batch_orders", "2"), ("max_active_deliveries", "4"),
                ("assignment_radius_km", "12")]
    cur.executemany(
        "MERGE system_settings AS t USING (VALUES (?, ?)) AS s(setting_key, "
        "setting_value) ON t.setting_key = s.setting_key"
        " WHEN MATCHED THEN UPDATE SET setting_value = s.setting_value"
        " WHEN NOT MATCHED THEN INSERT (setting_key, setting_value)"
        " VALUES (s.setting_key, s.setting_value);", settings)
    conn.commit()
    print(f"Done: {total:,} rows loaded into SQL Server.")


if __name__ == "__main__":
    main()
