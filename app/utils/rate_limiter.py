"""
Simple Rate Limiting Logic
"""
from app.database import get_db
from app.config import MAX_JOBS_PER_API_KEY, MAX_JOBS_PER_USER

def check_and_increment_rate_limits(user_id: str, api_key: str):
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT current_jobs FROM rate_limit_users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            user_jobs = row[0] if row else 0
            if user_jobs >= MAX_JOBS_PER_USER:
                return False, f"user limit exceeded ({user_jobs}/{MAX_JOBS_PER_USER})"

            row = conn.execute(
                "SELECT current_jobs FROM rate_limit_api_keys WHERE openai_api_key = ?",
                (api_key,)
            ).fetchone()
            key_jobs = row[0] if row else 0
            if key_jobs >= MAX_JOBS_PER_API_KEY:
                return False, f"api_key limit exceeded ({key_jobs}/{MAX_JOBS_PER_API_KEY})"

            conn.execute(
                "INSERT OR REPLACE INTO rate_limit_users (user_id, current_jobs) VALUES (?, ?)",
                (user_id, user_jobs + 1),
            )
            conn.execute(
                "INSERT OR REPLACE INTO rate_limit_api_keys (openai_api_key, current_jobs) VALUES (?, ?)",
                (api_key, key_jobs + 1),
            )
            return True, None
    except Exception as e:
        return False, f"rate limiter error: {e}"

def decrement_rate_limits(user_id: str, api_key: str):
    try:
        with get_db() as conn:
            conn.execute("UPDATE rate_limit_users SET current_jobs = MAX(0, current_jobs - 1) WHERE user_id = ?", (user_id,))
            conn.execute("UPDATE rate_limit_api_keys SET current_jobs = MAX(0, current_jobs - 1) WHERE openai_api_key = ?", (api_key,))
    except Exception:
        pass
