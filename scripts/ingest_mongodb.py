"""
SRS 3.11 - Data Ingestion: JSONL -> MongoDB.

Collections:
  * location_logs     - 263k simulated GPS points
  * tracking_events   - 70k order events
  * traffic_data      - 26k area/hour traffic snapshots
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

from pymongo import MongoClient  # noqa: E402

MONGO_DIR = os.path.join(config.DATA_DIR, "mongodb")
COLLECTIONS = ["location_logs", "tracking_events", "traffic_data"]
BATCH = 20000


def read_batches(path, size):
    """Yield lists of dicts from a JSON-Lines file."""
    buf = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                buf.append(json.loads(line))
            if len(buf) >= size:
                yield buf
                buf = []
    if buf:
        yield buf


def main():
    drop = "--drop" in sys.argv
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[config.MONGO_DB]
    print(f"Connected to MongoDB at {config.MONGO_URI} (db: {config.MONGO_DB})")

    for name in COLLECTIONS:
        if drop:
            db[name].drop()
            print(f"  dropped {name}")
        loaded = 0
        for batch in read_batches(os.path.join(MONGO_DIR, f"{name}.jsonl"), BATCH):
            if drop:
                db[name].insert_many(batch, ordered=False)
                loaded += len(batch)
            else:
                # skip rows already loaded (idempotent re-run)
                probe = db[name].count_documents({})
                if probe == 0:
                    db[name].insert_many(batch, ordered=False)
                    loaded += len(batch)
                else:
                    print(f"  {name} already has {probe:,} docs - skipping")
                    loaded = probe
                    break
        print(f"  {name:<20} {loaded:>9,} docs")
    print("MongoDB ingestion complete.")


if __name__ == "__main__":
    main()
