"""
Global Configuration
"""
import os

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "resume_analyzer.db")

MAX_FILE_SIZE =  5* 1024 * 1024  # 5MB

MAX_JOBS_PER_API_KEY = 20
MAX_JOBS_PER_USER = 1
JOB_CLEANUP_MINUTES = 60

# --- added ---
DB_BUSY_TIMEOUT_MS = 5000          # 5s wait on locks for the cleanup connection
CLEANUP_INTERVAL_SECONDS = 3600    # run cleanup every hour (if scheduler is used)
# --------------

OPENAI_API_URL = "https://api.openai.com/v1/responses"
OPENAI_TIMEOUT = 300

CHARS_PER_TOKEN = 4
MIN_OUTPUT_TOKENS = 16
EXTRACT_TOKEN_MULTIPLIER = 8
CLASSIFY_DEFAULT_TOKENS = 128

PARALLEL_STAGGER_DELAY = 0.25  # 250ms

PROMPTS_DIR = "prompts"

# --- Per-request debug logging ---
# Always sourced from config (not env) so behavior is explicit and testable.
DEBUG_REQUEST_LOG_ENABLED = True  # default: enabled
DEBUG_REQUEST_LOG_DIR = "./prl"   # per-request logs directory
DEBUG_REQUEST_LOG_REDACT_KEYS = ""  # comma-separated extra keys to redact (in addition to built-ins)

# --- Cleanup policy for per-request logs ---
PRL_MAX_BYTES = 50 * 1024 * 1024     # keep logs under 100 MB total
PRL_CLEAN_INTERVAL_SEC = 60     # run cleanup every hour

# ---------------- OpenAI limiting knobs ----------------
# OpenAI RPM limit (per API key)
OPENAI_RPM_PER_KEY = int(os.getenv("OPENAI_RPM_PER_KEY", "480"))

# If True -> fail fast (raise 429). If False -> block (delay) until allowed.
OPENAI_RPM_FAIL_FAST = os.getenv("OPENAI_RPM_FAIL_FAST", "0") == "1"

# When blocking, the maximum total delay budget in milliseconds.
# Default 1 hour: effectively "wait until free" for typical bursts.
OPENAI_RPM_MAX_DELAY_MS = int(os.getenv("OPENAI_RPM_MAX_DELAY_MS", "3600000"))

# Cap concurrent in-flight OpenAI calls per API key. 0 disables.
OPENAI_MAX_CONCURRENCY_PER_KEY = int(os.getenv("OPENAI_MAX_CONCURRENCY_PER_KEY", "20"))

# Optional (future): use RedisBucket for cluster-wide RPM
OPENAI_REDIS_URL = os.getenv("OPENAI_REDIS_URL", "")