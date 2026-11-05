-- ============================================================
--  MOON Light - Food Delivery Optimization System
--  Reference T-SQL schema for the DATA WAREHOUSE database
--  (matches the CSV / JSONL deliverables in the data/ folder,
--   see data/README.txt for row counts).
--
--  Target: SQL Server 2019+ (ODBC Driver 17)   City: Karachi
--
--  Two databases make up the deliverable:
--    * food_delivery_sys  - live operational DB created by the app
--      (scripts/bootstrap_sql_server.py, tables match app/models.py)
--    * food_delivery      - this warehouse, loaded historically by
--      scripts/ingest_sql_server.py from data/sql_server/*.csv
--
--  Load with:   python scripts/ingest_sql_server.py
--  (or run this file in SSMS first, then use the Import Wizard)
-- ============================================================

CREATE DATABASE food_delivery;
GO
USE food_delivery;
GO

-- ------------------------------------------------------------
-- clean slate (circular FKs are handled in the ingest script)
-- ------------------------------------------------------------
DROP TABLE IF EXISTS partner_status_history;
DROP TABLE IF EXISTS admin_audit_log;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS ratings;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS menu_items;
DROP TABLE IF EXISTS delivery_partners;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS restaurants;
DROP TABLE IF EXISTS users;
GO

-- ------------------------------------------------------------
-- SRS 3.1 - Auth: role-based users
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id        INT           NOT NULL PRIMARY KEY,
    username       NVARCHAR(60)  NOT NULL UNIQUE,
    password_hash  NVARCHAR(200) NOT NULL,
    role           NVARCHAR(20)  NOT NULL,          -- Admin / Customer / Delivery Partner
    is_active      BIT           NOT NULL DEFAULT 1,
    created_at     DATETIME2(0)  NOT NULL,
    last_login     DATETIME2(0)  NULL
);
GO

CREATE TABLE restaurants (
    restaurant_id  INT           NOT NULL PRIMARY KEY,
    name           NVARCHAR(120) NOT NULL,
    cuisine        NVARCHAR(60)  NOT NULL,
    area           NVARCHAR(60)  NOT NULL,          -- Karachi area (Bahadurabad, Clifton, ...)
    latitude       FLOAT         NOT NULL,
    longitude      FLOAT         NOT NULL,
    open_time      TIME(0)       NOT NULL,
    close_time     TIME(0)       NOT NULL,
    avg_rating     FLOAT         NULL DEFAULT 0
);
GO

CREATE TABLE customers (
    customer_id      INT           NOT NULL PRIMARY KEY,
    user_id          INT           NOT NULL REFERENCES users (user_id),
    name             NVARCHAR(100) NOT NULL,
    phone            NVARCHAR(20)  NULL,
    address          NVARCHAR(255) NULL,
    area             NVARCHAR(80)  NULL,
    latitude         FLOAT         NULL,
    longitude        FLOAT         NULL,
    food_preferences NVARCHAR(255) NULL
);
GO

CREATE TABLE delivery_partners (
    partner_id        INT          NOT NULL PRIMARY KEY,
    user_id           INT          NOT NULL REFERENCES users (user_id),
    name              NVARCHAR(100) NOT NULL,
    phone             NVARCHAR(20) NULL,
    vehicle_type      NVARCHAR(30) NOT NULL,
    experience_months INT          NOT NULL DEFAULT 0,
    status            NVARCHAR(20) NOT NULL DEFAULT 'offline',
    current_lat       FLOAT        NULL,
    current_lon       FLOAT        NULL,
    avg_rating        FLOAT        NULL DEFAULT 0,
    total_deliveries  INT          NOT NULL DEFAULT 0
);
GO

-- SRS 3.3 - Restaurants + menu
CREATE TABLE menu_items (
    item_id        INT            NOT NULL PRIMARY KEY,
    restaurant_id  INT            NOT NULL REFERENCES restaurants (restaurant_id),
    name           NVARCHAR(120)  NOT NULL,
    price          DECIMAL(10, 2) NOT NULL CHECK (price >= 0),  -- PKR
    is_available   BIT            NOT NULL DEFAULT 1
);
GO

-- SRS 3.4 - Orders lifecycle
CREATE TABLE orders (
    order_id                  INT            NOT NULL PRIMARY KEY,
    customer_id               INT            NOT NULL REFERENCES customers (customer_id),
    restaurant_id             INT            NOT NULL REFERENCES restaurants (restaurant_id),
    partner_id                INT            NULL,             -- FK added after load (below)
    order_time                DATETIME2(0)   NOT NULL,
    accepted_time             DATETIME2(0)   NULL,
    prepared_time             DATETIME2(0)   NULL,
    dispatched_time           DATETIME2(0)   NULL,
    delivered_time            DATETIME2(0)   NULL,
    status                    NVARCHAR(20)   NOT NULL,         -- placed/prepared/dispatched/delivered/cancelled/rejected
    cancel_reason             NVARCHAR(255)  NULL,
    subtotal                  DECIMAL(10, 2) NOT NULL,
    delivery_fee              DECIMAL(10, 2) NOT NULL,
    total_amount              DECIMAL(10, 2) NOT NULL,
    distance_km               FLOAT          NULL,
    partner_to_restaurant_km  FLOAT          NULL,
    prep_time_min             FLOAT          NULL,
    traffic_level             NVARCHAR(10)   NULL,             -- low / medium / high
    partner_current_orders    INT            NULL DEFAULT 0,
    actual_delivery_min       FLOAT          NULL,
    weather                   NVARCHAR(20)   NULL,
    batched                   BIT            NOT NULL DEFAULT 0
);
GO

CREATE TABLE order_items (
    order_id  INT            NOT NULL REFERENCES orders (order_id),
    item_id   INT            NOT NULL REFERENCES menu_items (item_id),
    quantity  INT            NOT NULL CHECK (quantity > 0),
    price     DECIMAL(10, 2) NOT NULL,
    CONSTRAINT PK_order_items PRIMARY KEY (order_id, item_id)
);
GO

-- SRS 3.14 - Feedback / ratings
CREATE TABLE ratings (
    rating_id         INT           NOT NULL PRIMARY KEY,
    order_id          INT           NOT NULL REFERENCES orders (order_id),
    customer_id       INT           NOT NULL REFERENCES customers (customer_id),
    restaurant_id     INT           NOT NULL REFERENCES restaurants (restaurant_id),
    partner_id        INT           NULL REFERENCES delivery_partners (partner_id),
    restaurant_rating INT           NOT NULL CHECK (restaurant_rating BETWEEN 1 AND 5),
    partner_rating    INT           NULL     CHECK (partner_rating BETWEEN 1 AND 5),
    comment           NVARCHAR(255) NULL,
    created_at        DATETIME2(0)  NOT NULL
);
GO

CREATE TABLE notifications (
    notif_id     INT           NOT NULL PRIMARY KEY,
    user_id      INT           NOT NULL REFERENCES users (user_id),
    message      NVARCHAR(255) NOT NULL,
    type         NVARCHAR(30)  NOT NULL,
    created_at   DATETIME2(0)  NOT NULL,
    is_read      BIT           NOT NULL DEFAULT 0,
    delivered_at DATETIME2(0)  NULL,
    read_at      DATETIME2(0)  NULL
);
GO

CREATE TABLE partner_status_history (
    partner_id  INT          NOT NULL REFERENCES delivery_partners (partner_id),
    date        DATE         NOT NULL,
    status      NVARCHAR(20) NOT NULL,
    updated_at  DATETIME2(0) NOT NULL,
    CONSTRAINT PK_partner_status_history PRIMARY KEY (partner_id, date)
);
GO

-- SRS 3.13 - Admin audit trail (data-warehouse copy)
CREATE TABLE admin_audit_log (
    log_id     INT           NOT NULL PRIMARY KEY,
    admin_id   INT           NULL REFERENCES users (user_id),
    action     NVARCHAR(40)  NOT NULL,
    target     NVARCHAR(80)  NULL,
    notes      NVARCHAR(255) NULL,
    created_at DATETIME2(0)  NOT NULL
);
GO

-- ------------------------------------------------------------
-- foreign key that must exist only after delivery_partners load
-- ------------------------------------------------------------
IF OBJECT_ID('FK_orders_partner', 'F') IS NULL
   ALTER TABLE orders
       ADD CONSTRAINT FK_orders_partner
       FOREIGN KEY (partner_id) REFERENCES delivery_partners (partner_id);
GO

-- ------------------------------------------------------------
-- hot-path indexes (matching how the analytics queries filter)
-- ------------------------------------------------------------
CREATE INDEX ix_orders_status      ON orders (status);
CREATE INDEX ix_orders_partner     ON orders (partner_id);
CREATE INDEX ix_orders_customer    ON orders (customer_id);
CREATE INDEX ix_orders_order_time  ON orders (order_time);
CREATE INDEX ix_menu_items_rest    ON menu_items (restaurant_id);
CREATE INDEX ix_ratings_order      ON ratings (order_id);
CREATE INDEX ix_notifs_user        ON notifications (user_id, is_read);
CREATE INDEX ix_users_role         ON users (role);
GO

-- ------------------------------------------------------------
-- MongoDB (optional high-volume store) - loaded with
--   python scripts/ingest_mongodb.py
-- documents:
--   location_logs   {order_id, partner_id, seq, lat, lon, speed_kmh, timestamp}
--   traffic_data    {area, date, hour, day_of_week, traffic_level, avg_speed_kmh, weather, incident, timestamp}
--   tracking_events {order_id, event, timestamp, note}
-- ------------------------------------------------------------
