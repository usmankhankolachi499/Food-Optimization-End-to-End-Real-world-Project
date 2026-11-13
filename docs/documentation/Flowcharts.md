# Flowcharts — Food Delivery Optimization System

## 1. Order Placement + ML ETA (Customer Checkout)

```mermaid
flowchart TD
    A[Customer adds items to cart] --> B{Restaurant<br/>is_open_now?}
    B -- No --> Z[Flash warning,<br/>back to restaurants]
    B -- Yes --> C[Checkout form:<br/>address, location, payment]
    C --> D{Valid input?}
    D -- No --> C
    D -- Yes --> E[Calculate distance<br/>haversine + delivery fee]
    E --> F[Call routing.estimate_eta]
    F --> G[ml_bridge.predict_eta]
    G --> H{ML model<br/>available?}
    H -- Yes --> I[Load pkl model,<br/>build 28-feature row,<br/>predict]
    H -- No --> J[Fallback heuristic:<br/>prep + distance/speed x traffic]
    I --> K[Save order with<br/>estimated_delivery_min]
    J --> K
    K --> L[Notify customer,<br/>partner, admin]
    L --> M{Auto-assign<br/>setting on?}
    M -- Yes --> N[Assignment engine]
    M -- No --> O[Order waits in queue]
```

## 2. Order Assignment (Distance + Workload Scoring)

```mermaid
flowchart TD
    A[Order needs a rider] --> B{Auto-assign?}
    B -- Manual --> C[Admin picks rider<br/>or clicks Assign All]
    B -- Auto --> D[ranked_partners:<br/>list active riders]
    D --> E[For each rider compute:<br/>distance to pickup,<br/>active workload, rating]
    E --> F{ML score hook<br/>available?}
    F -- Yes --> G[Add ML partner score]
    F -- No --> H[score = distance + workload x 2]
    G --> I[Sort by eligibility,<br/>score, distance]
    H --> I
    I --> J{Best rider<br/>under capacity?}
    J -- Yes --> K[Assign order,<br/>notify rider]
    J -- No --> L{Auto-hire<br/>enabled?}
    L -- Yes --> M[Hire new rider,<br/>then assign]
    L -- No --> N[Force assign to<br/>least-workload rider]
    M --> K
    N --> K
```

## 3. Delivery Lifecycle (Rider + Tracking)

```mermaid
flowchart TD
    A[Rider accepts request] --> B[Mark prepared]
    B --> C[Dispatch: start delivery]
    C --> D[Rider moves: GPS ping every update<br/>lat, lon, speed saved]
    D --> E[Customer tracking page:<br/>Leaflet map follows rider]
    D --> F[Simulator advances<br/>lifecycle automatically]
    E --> G[Mark delivered]
    F --> G
    G --> H[Notification: order delivered]
    H --> I{Customer leaves<br/>feedback?}
    I -- Yes --> J[Rating saved,<br/>restaurant + rider averages update]
    I -- No --> K[Order archived in history]
    J --> K
```

## 4. ML Model Pipeline (Training → Prediction)

```mermaid
flowchart LR
    A[data/raw<br/>orders_raw.csv] --> B[clean_data.py<br/>dedupe, fix values]
    B --> C[data/cleaned]
    C --> D[ML dataset build<br/>13,314 records]
    D --> E[train_model.py<br/>one-hot encoding<br/>80/20 train-test split]
    E --> F{Compare models}
    F --> G[GradientBoosting<br/>old baseline ~75%]
    F --> H[HistGradientBoosting<br/>R2 0.936 WINNER]
    H --> I[delivery_time_model.pkl<br/>model_features.pkl]
    I --> J[Web app checkout:<br/>predict_eta per order]
```

## 5. Live Demo Simulator (Background Thread)

```mermaid
flowchart TD
    A[App starts,<br/>simulator thread on] --> B{live_order_simulation<br/>setting?}
    B -- Off --> C{Auto-hire needed?}
    B -- On --> D[Spawn 2 orders/min<br/>notes tagged SIM:]
    D --> E[Advance lifecycle:<br/>confirmed > prepared > dispatched > delivered]
    C -- Yes --> F[Hire rider<br/>max 3 per tick,<br/>fleet cap 14]
    C -- No --> G[Cleanup old SIM orders<br/>older than 3 days]
    E --> C
    F --> G
```

> Simulator-tagged orders (`SIM:` prefix in notes) never touch real customer
> orders — demo data stays separate.
