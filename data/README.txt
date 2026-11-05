Food Delivery Optimization System - synthetic data
City: Karachi | Period: 2026-07-01 to 2026-09-30 | Seed: 42

ROW COUNTS
  users                                       853
  customers                                   800
  restaurants                                  40
  menu_items                                  362
  delivery_partners                            50
  orders                                   15,000
  order_items                              32,424
  ratings                                   9,259
  notifications                            55,460
  partner_status_history                    4,600
  admin_audit_log                             120
  location_logs (MongoDB)                 263,758
  traffic_data (MongoDB)                   26,496
  tracking_events (MongoDB)                70,420
  orders: delivered                        13,314
  orders: dispatched(stuck)                     0
  orders: cancelled                         1,061
  orders: rejected                            147
  orders: placed(pending)                      37
  traffic: incidents                          148
  traffic: rain hours                       4,032

FOLDERS
  sql_server/  CSV per table, load into SQL Server (Import Wizard, BULK INSERT or pandas.to_sql)
  mongodb/     JSON Lines, load with:
               mongoimport --db food_delivery --collection location_logs   --file mongodb/location_logs.jsonl
               mongoimport --db food_delivery --collection traffic_data    --file mongodb/traffic_data.jsonl
               mongoimport --db food_delivery --collection tracking_events --file mongodb/tracking_events.jsonl
  ml/          delivery_time_dataset.csv  (target: actual_delivery_min)
  raw/         DIRTY copies for cleaning / validation module; see data_quality_issues.json

SRS COVERAGE
  3.1  Auth           -> users (role-based, hashed passwords)
  3.2  Customer       -> customers (preferences, order history)
  3.3  Restaurant     -> restaurants + menu_items (cuisine, hours, availability)
  3.4  Orders         -> orders (placed/prepared/dispatched/delivered/cancelled/rejected)
  3.5  Partners       -> delivery_partners + partner_status_history
  3.6  Tracking       -> location_logs + tracking_events (MongoDB)
  3.7  Route/Traffic  -> traffic_data (weather + incidents + speed)
  3.8  Assignment     -> orders.batched + workload-aware partner selection
  3.9  Analytics/ML   -> ml/delivery_time_dataset.csv with rich features
  3.10 Data Processing-> raw/ with documented quality issues
  3.11 Storage        -> sql_server/ (T-SQL) + mongodb/ (JSONL)
  3.12 Dashboard      -> ready (data feeds dashboards)
  3.13 Admin          -> admin_audit_log
  3.14 Notifications  -> notifications (delivered_at/read_at lifecycle)
  3.15 Feedback       -> ratings (J-shaped distribution)

LOGIN (demo only)
  Every user has the password: Password@123
  Admins: admin1, admin2, admin3 | Partners: dp001... | Customers: see users.csv

ASSUMPTIONS (per SRS page 19)
  - Live GPS API not integrated; simulated GPS trails used (allowed by SRS page 24).
  - Live traffic API not used; synthetic traffic follows peak-hour patterns.
  - Weather and road incidents are simulated.
  - Demo password `Password@123`; production should use bcrypt/argon2.
  - 'Stuck in dispatched' orders simulate real-world partner app crashes.
  - Batch delivery ~12% (real-world Karachi dense areas: 15-20%).
  - Ratings follow J-shaped distribution (typical for delivery platforms).
