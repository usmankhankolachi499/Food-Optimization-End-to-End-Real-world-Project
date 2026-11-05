"""Convenience wrapper for loading the optional demo fixtures.

Usage:
    python seed_demo.py
    python seed_demo.py --with-orders
"""
from __future__ import annotations

import sys

from app import create_app
from app.seed import seed_demo

# The demo summary contains the rupee symbol; avoid UnicodeEncodeError on
# legacy Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = create_app()

with app.app_context():
    print(seed_demo(with_orders="--with-orders" in sys.argv[1:]))
