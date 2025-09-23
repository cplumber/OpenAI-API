"""
Job Creation and Status Management
"""
import json
from app.database import get_db

def create_job(job_id: str, user_id: str, api_key: str) -> bool:
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO jobs (job_id, user_id, openai_api_key, status, progress) VALUES (?, ?, ?, 'queued', 0)", (job_id, user_id, api_key))
        return True
    except Exception:
        return False

def update_job_status(job_id: str, status: str, progress: int = None, result: dict = None, error_message: str = None):
    try:
        with get_db() as conn:
            if status in ("completed", "failed"):
                if result is not None:
                    conn.execute("UPDATE jobs SET status = ?, progress = ?, result = ?, completed_at = CURRENT_TIMESTAMP WHERE job_id = ?", (status, 100, json.dumps(result), job_id))
                else:
                    conn.execute("UPDATE jobs SET status = ?, progress = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP WHERE job_id = ?", (status, 100, error_message, job_id))
            else:
                if progress is not None:
                    conn.execute("UPDATE jobs SET status = ?, progress = ? WHERE job_id = ?", (status, progress, job_id))
                else:
                    conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
    except Exception:
        pass
