import json
import sqlite3
from pathlib import Path

class EventOutbox:
    """Durable deduplication and retries when Kafka is unavailable.

    A send/ack crash may replay an event; downstream persistence is idempotent.
    One ingestion process owns this journal. Never run multiple ingest workers
    against the same source; API replicas use BUOY_INGESTION_ENABLED=false.
    """
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0)")
        self.db.commit()

    def add(self, observation):
        cursor = self.db.execute("INSERT OR IGNORE INTO outbox(id,payload) VALUES (?,?)",
                                 (observation.identity, json.dumps(observation.event())))
        self.db.commit()
        return cursor.rowcount == 1

    def pending(self):
        return [(key, json.loads(payload)) for key, payload in self.db.execute(
            "SELECT id,payload FROM outbox WHERE published=0 ORDER BY rowid LIMIT 100")]

    def acknowledge(self, key):
        self.db.execute("UPDATE outbox SET published=1 WHERE id=?", (key,))
        self.db.commit()

    def close(self): self.db.close()
