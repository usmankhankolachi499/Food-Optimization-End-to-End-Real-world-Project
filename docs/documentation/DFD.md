# Data Flow Diagrams (DFD) — Food Delivery Optimization System

## Level 0 — Context Diagram

The whole system as one process, with the four external entities.

```mermaid
flowchart LR
    C[Customer]
    R[Rider / Delivery Partner]
    A[Admin]
    D[(Data Sources<br/>raw CSV / JSONL)]

    P((Food Delivery<br/>Optimization System))

    C -- "order request / payment / feedback" --> P
    P -- "ETA, live tracking, status" --> C

    R -- "location pings, status update" --> P
    P -- "delivery request, earnings" --> R

    A -- "settings, assignment, management" --> P
    P -- "analytics, reports, audit trail" --> A

    D -- "historical data (pipeline ingest)" --> P
```

## Level 1 — Major Sub-Processes

```mermaid
flowchart TB
    subgraph PROCESSES
        P1[1.0 Authentication<br/>& Roles]
        P2[2.0 Ordering<br/>Cart + Checkout]
        P3[3.0 ML ETA<br/>Prediction]
        P4[4.0 Assignment<br/>Engine]
        P5[5.0 Live Tracking<br/>+ GPS Log]
        P6[6.0 Analytics<br/>& Reports]
        P7[7.0 Data<br/>Pipeline]
    end

    subgraph STORES
        S1[(users / profiles)]
        S2[(orders / order_items)]
        S3[(system_settings)]
        S4[(location_logs)]
        S5[(feedback)]
        S6[(MongoDB mirror)]
        S7[(data/ warehouse)]
    end

    CUST([Customer])
    PART([Rider])
    ADM([Admin])

    CUST --> P1 --> S1
    CUST --> P2 --> S2
    P2 -- "order placed" --> P3
    S3 -- "traffic factor, speed" --> P3
    P3 -- "ETA minutes" --> S2
    S2 -- "unassigned orders" --> P4
    PART -- "availability" --> S1
    P4 -- "delivery request" --> PART
    PART -- "status + GPS" --> P5 --> S4
    S4 -- "mirror pings" --> S6
    S2 --> P6 --> ADM
    S5 --> P6
    S7 --> P7 --> P3
```

## Level 1 — Process Descriptions

| # | Process | Inputs | Outputs | Key Files |
|---|---------|--------|---------|-----------|
| 1.0 | Authentication | login form, staff code | session, role redirect | `app/blueprints/auth.py` |
| 2.0 | Ordering | cart items, address, payment | order + order_items rows | `app/blueprints/customer.py` |
| 3.0 | ML ETA Prediction | distance, prep time, traffic, hour | `estimated_delivery_min` | `ml/predictor.py`, `app/services/ml_bridge.py` |
| 4.0 | Assignment | unassigned orders, rider states | assigned order + audit entry | `app/services/assignment.py`, `simulator.py` |
| 5.0 | Tracking | rider GPS pings, status changes | location_logs rows, map view | `app/services/tracking.py` |
| 6.0 | Analytics | orders, feedback, audit | charts, CSV reports | `app/services/analytics.py` |
| 7.0 | Data Pipeline | raw CSV/JSONL | cleaned files, warehouse, ML dataset | `scripts/clean_data.py`, `ingest_*.py` |

## Data Dictionary (main flows)

| Flow | Content | Source → Sink |
|---|---|---|
| order-request | items, qty, address, payment method | Customer → 2.0 |
| eta-prediction | minutes (integer), source = "ml" | 3.0 → orders table → Customer |
| assignment-request | order id, ranked riders (distance + workload) | 4.0 → Rider |
| gps-ping | lat, lon, speed, seq, order id | Rider → 5.0 → location_logs |
| feedback | rating 1–5, comment | Customer → feedback table |
| cleaned-dataset | 14,908 orders, 29,100 GPS pings | 7.0 → data/cleaned |
