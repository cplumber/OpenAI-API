"""
SQLite Database Connection
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import threading
import time  # <-- added

from app.config import DATABASE_URL, JOB_CLEANUP_MINUTES, DB_BUSY_TIMEOUT_MS, CLEANUP_INTERVAL_SECONDS

_local = threading.local()

def get_db_connection():
    if not hasattr(_local, 'connection') or _local.connection is None:
        _local.connection = sqlite3.connect(DATABASE_URL, check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
    return _local.connection

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def init_database():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                openai_api_key TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                result TEXT,
                error_message TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit_users (
                user_id TEXT PRIMARY KEY,
                current_jobs INTEGER DEFAULT 0,
                last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit_api_keys (
                openai_api_key TEXT PRIMARY KEY,
                current_jobs INTEGER DEFAULT 0,
                last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

# ---------- added: dedicated connection for cleanup ----------

def _tune_conn(conn: sqlite3.Connection):
    """Apply pragmas that reduce contention and make cleanup safer."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")

@contextmanager
def _cleanup_conn():
    """Separate connection for cleanup to avoid sharing request thread's connection."""
    conn = sqlite3.connect(
        DATABASE_URL,
        check_same_thread=False,
        timeout=DB_BUSY_TIMEOUT_MS / 1000.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    try:
        _tune_conn(conn)
        yield conn
    finally:
        conn.close()

# ---------- replaced: cleanup_old_jobs now uses separate connection, batches, retries ----------

def cleanup_old_jobs():
    """
    Deletes old jobs in small batches using a dedicated connection.
    Retries up to 5 times with 5s sleep on lock/busy. Keeps lock windows tiny.
    Returns number of rows deleted in the last batch (0 if nothing to delete).
    """
    cutoff = datetime.now() - timedelta(minutes=JOB_CLEANUP_MINUTES)
    attempts = 5
    batch_size = 500

    for attempt in range(attempts):
        try:
            with _cleanup_conn() as conn:
                conn.execute("BEGIN")
                rows = conn.execute(
                    "SELECT job_id FROM jobs WHERE created_at < ? LIMIT ?",
                    (cutoff, batch_size),
                ).fetchall()
                if not rows:
                    conn.commit()
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    return 0

                ids = [r[0] for r in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(f"DELETE FROM jobs WHERE job_id IN ({placeholders})", ids)
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                return len(ids)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" in msg or "busy" in msg) and attempt < attempts - 1:
                time.sleep(5)
                continue
            raise

#  tiny scheduler you can call from FastAPI startup ----------

import threading, time
from datetime import datetime
from app.config import CLEANUP_INTERVAL_SECONDS
from app.database import cleanup_old_jobs

def start_cleanup_scheduler():
    """
    Starts a background daemon thread that runs cleanup once per hour.
    Call this from your FastAPI startup event:
        from app.database import start_cleanup_scheduler
        start_cleanup_scheduler()
    """
    def _loop():
        while True:
            try:
                deleted = cleanup_old_jobs()
                print(f"[{datetime.now().isoformat()}] cleanup_old_jobs ran, deleted {deleted} rows")
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] cleanup_old_jobs error: {e}")
            time.sleep(CLEANUP_INTERVAL_SECONDS)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

