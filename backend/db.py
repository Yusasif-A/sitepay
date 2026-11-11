"""
One shared MongoDB client for the whole backend (same pattern as Avalio).

`MONGO_URI=mongomock://` swaps in an in-memory database for local
development and the test suite.
"""

import logging
import threading
from typing import Optional

from pymongo import ASCENDING
from pymongo.database import Database

import config

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()
_indexed = False


def _make_client():
    uri = config.MONGO_URI
    if not uri:
        raise RuntimeError("MONGO_URI is not set — see .env.example")
    if uri.startswith("mongomock://"):
        import mongomock
        logger.warning("⚠️ Using in-memory mongomock database — data is lost on restart")
        return mongomock.MongoClient()

    from pymongo import MongoClient
    from pymongo.server_api import ServerApi
    client = MongoClient(uri, server_api=ServerApi("1"), maxPoolSize=50, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    logger.info(f"✅ Connected to MongoDB (db: {config.MONGO_DB_NAME})")
    return client


def get_db() -> Database:
    global _client, _indexed
    if _client is None:
        with _lock:
            if _client is None:
                _client = _make_client()
    db = _client.get_database(config.MONGO_DB_NAME)
    if not _indexed:
        with _lock:
            if not _indexed:
                _ensure_indexes(db)
                _indexed = True
    return db


def reset_for_tests():
    """Drop the cached client so a test gets a fresh in-memory database."""
    global _client, _indexed
    _client = None
    _indexed = False


def _ensure_indexes(db: Database) -> None:
    db.supervisors.create_index("email", unique=True)
    db.supervisors.create_index("supervisor_id", unique=True)
    db.sites.create_index("site_id", unique=True)
    db.sites.create_index("supervisor_id")
    db.workers.create_index("worker_id", unique=True)
    db.workers.create_index("phone", unique=True)
    db.workers.create_index([("supervisor_id", ASCENDING), ("site_id", ASCENDING)])
    db.attendance.create_index([("worker_id", ASCENDING), ("date", ASCENDING)], unique=True)
    db.attendance.create_index([("site_id", ASCENDING), ("date", ASCENDING)])
    db.evidence.create_index("evidence_id", unique=True)
    db.evidence.create_index([("worker_id", ASCENDING), ("date", ASCENDING)])
    db.pay_runs.create_index("run_id", unique=True)
    db.pay_runs.create_index("supervisor_id")
    db.pay_lines.create_index([("run_id", ASCENDING), ("worker_id", ASCENDING)], unique=True)
    db.chat_state.create_index("phone", unique=True)
    db.shifts.create_index([("worker_id", ASCENDING), ("date", ASCENDING)], unique=True)
    db.shifts.create_index([("site_id", ASCENDING), ("date", ASCENDING)])
