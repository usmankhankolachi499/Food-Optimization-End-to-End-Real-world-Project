# ER Diagram — Food Delivery Optimization System

Entity-Relationship diagram of the 12 application tables
(SQL Server database: `food_delivery_sys`).

## Entities and Relationships (Mermaid)

```mermaid
erDiagram
    USERS ||--o| CUSTOMER_PROFILES : "1:1 customer profile"
    USERS ||--o| DELIVERY_PARTNER_PROFILES : "1:1 partner profile"
    USERS ||--o{ ORDERS : "places (customer)"
    USERS ||--o{ ORDERS : "delivers (partner)"
    USERS ||--o{ NOTIFICATIONS : "receives"
    USERS ||--o{ AUDIT_LOG : "acts (admin)"
    USERS ||--o{ LOCATION_LOGS : "pings (partner)"
    USERS |o--o{ FEEDBACK : "writes (customer)"

    RESTAURANTS ||--o{ MENU_ITEMS : "offers"
    RESTAURANTS ||--o{ ORDERS : "fulfils"
    RESTAURANTS |o--o{ FEEDBACK : "rated by"
    RESTAURANTS |o--o{ CUSTOMER_PROFILES : "favourite of"

    ORDERS ||--o{ ORDER_ITEMS : "contains"
    ORDERS ||--o{ LOCATION_LOGS : "tracked by"
    ORDERS ||--o| FEEDBACK : "receives"

    MENU_ITEMS ||--o{ ORDER_ITEMS : "ordered as"

    USERS {
        int id PK
        string name
        string username UK
        string email UK
        string phone
        string role "customer | delivery | admin"
        string password_hash "pbkdf2"
        bool is_active
        datetime created_at
    }

    CUSTOMER_PROFILES {
        int user_id PK,FK
        string address
        string city
        float latitude
        float longitude
        int favorite_restaurant_id FK
    }

    DELIVERY_PARTNER_PROFILES {
        int user_id PK,FK
        string vehicle_type
        string vehicle_number
        bool is_available
        float current_lat
        float current_lng
        float rating_avg
        int rating_count
        int total_delivered
    }

    RESTAURANTS {
        int id PK
        string name
        string cuisine
        string address
        float latitude
        float longitude
        time opening_time
        time closing_time
        string image_url
        bool is_active
        float rating_avg
    }

    MENU_ITEMS {
        int id PK
        int restaurant_id FK
        string name
        string category
        float price
        int prep_time_min
        bool is_available
    }

    ORDERS {
        int id PK
        string order_number UK
        int customer_id FK
        int restaurant_id FK
        int delivery_partner_id FK
        string status "placed|confirmed|prepared|dispatched|delivered|cancelled"
        decimal subtotal
        decimal delivery_fee
        decimal total_amount
        float distance_km
        int estimated_delivery_min "ML predicted"
        datetime placed_at
        datetime delivered_at
        float delivery_lat
        float delivery_lng
        string notes
    }

    ORDER_ITEMS {
        int id PK
        int order_id FK
        int menu_item_id FK
        int quantity
        decimal price
    }

    NOTIFICATIONS {
        int id PK
        int user_id FK
        string title
        string message
        string kind
        datetime read_at
    }

    FEEDBACK {
        int id PK
        int order_id FK,UK
        int customer_id FK
        int restaurant_id FK
        int partner_id FK
        int rating "1-5"
        string comment
    }

    LOCATION_LOGS {
        int id PK
        int order_id FK
        int partner_id FK
        float lat
        float lon
        int seq
        float speed_kmh
        datetime recorded_at
    }

    SYSTEM_SETTINGS {
        int id PK
        string key UK
        string value
        string description
    }

    AUDIT_LOG {
        int id PK
        int admin_id FK
        string action
        string entity_type
        string details
        datetime created_at
    }
```

## Cardinality Summary

| Relationship | Cardinality | Note |
|---|---|---|
| User → CustomerProfile | 1 : 1 | one profile per customer account |
| User → DeliveryPartnerProfile | 1 : 1 | one profile per rider account |
| User → Orders | 1 : N | as customer or as delivery partner |
| Restaurant → MenuItems | 1 : N | 12 restaurants, 125+ items |
| Order → OrderItems | 1 : N | line items of the bill |
| Order → Feedback | 1 : 1 | one rating per order (unique) |
| Order → LocationLogs | 1 : N | GPS pings during delivery |
| MenuItem → OrderItems | 1 : N | which item was bought |
| User → Notifications | 1 : N | bell inbox |

> Roles live in `users.role` (customer / delivery / admin), so the three
> account types share one authentication table — role guards protect every
> dashboard.
