# app/core/ai_gateway.py
"""
Single entry point for ALL OpenAI calls in this service.

Pinned dependency:
    pyrate-limiter==3.9.0

What it does:
- Enforces per-API-key RPM (requests per minute) using pyrate-limiter.
- Caps in-flight concurrency per API key using a keyed threading.Semaphore.
- Translates rate-limit breaches into proper HTTP 429 (with Retry-After).
- Centralizes all outbound OpenAI traffic so no path can bypass limits.
- Ready to switch to Redis-backed limiter later without touching call sites.

Usage:
    from app.core.ai_gateway import call_openai_rate_limited

    resp = call_openai_rate_limited(
        api_key, model, prompt_text, max_output_tokens, temperature_zero
    )

Batch execution:
    Pass call_openai_rate_limited into your parallel executor so EACH
    prompt consumes an RPM token and a concurrency slot.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import os
from threading import Lock, Semaphore

from fastapi import HTTPException
# pyrate-limiter 3.9.0 API
from pyrate_limiter import (
    Duration,
    RequestRate,
    Limiter,
    MemoryListBucket,      # default (per-process) backend
    BucketFullException,   # raised when delay=False and bucket is full
)

# -------------------------- Config (import with fallbacks) --------------------

try:
    from app.config import (
        OPENAI_RPM_PER_KEY,               # int, e.g. 480 (headroom under vendor 500)
        OPENAI_RPM_FAIL_FAST,             # bool: True => raise immediately; False => block until token
        OPENAI_MAX_CONCURRENCY_PER_KEY,   # int: 0 disables concurrency limiting; else blocks until free slot
        OPENAI_REDIS_URL,                 # optional: enable Redis-backed limiter later
    )
except Exception:
    # Safe fallbacks (env-overridable) in case config import order is early
    OPENAI_RPM_PER_KEY = int(os.getenv("OPENAI_RPM_PER_KEY", "480"))
    OPENAI_RPM_FAIL_FAST = os.getenv("OPENAI_RPM_FAIL_FAST", "0") == "1"
    OPENAI_MAX_CONCURRENCY_PER_KEY = int(os.getenv("OPENAI_MAX_CONCURRENCY_PER_KEY", "20"))
    OPENAI_REDIS_URL = os.getenv("OPENAI_REDIS_URL", "")

# -------------------------- Custom Exceptions --------------------------------

class OpenAIRateLimitError(HTTPException):
    """
    Raised when RPM guard rejects a call (or when fail-fast is enabled).
    Produces HTTP 429 with an optional Retry-After header.
    """
    def __init__(self, detail: str, retry_after: Optional[float] = None):
        headers: Dict[str, str] = {}
        if retry_after is not None and retry_after >= 0:
            # Round up to whole seconds for header
            headers["Retry-After"] = str(int(retry_after + 0.999))
        super().__init__(status_code=429, detail=detail, headers=headers)

# -------------------------- RPM Limiter Builder -------------------------------

def _build_limiter() -> Limiter:
    """
    Build a per-process limiter now; switch to Redis-backed later
    by swapping the bucket class (kept commented below).
    """
    rate = RequestRate(OPENAI_RPM_PER_KEY, Duration.MINUTE)

    # Default: in-memory (per-process) bucket
    bucket_class = MemoryListBucket
    bucket_kwargs: Dict[str, Any] = {}

    # # Optional: switch to Redis (cluster-wide RPM) when ready (pyrate-limiter 3.9.0 supports RedisBucket):
    # if OPENAI_REDIS_URL:
    #     # pip install redis
    #     import redis
    #     from pyrate_limiter import RedisBucket
    #     pool = redis.ConnectionPool.from_url(OPENAI_REDIS_URL)
    #     bucket_class = RedisBucket
    #     bucket_kwargs = {"redis_pool": redis.Redis(connection_pool=pool)}

    return Limiter(rate, bucket_class=bucket_class, bucket_kwargs=bucket_kwargs)

_limiter: Limiter = _build_limiter()

# -------------------------- Per-Key Concurrency Guard -------------------------

_sem_lock = Lock()
_sems: Dict[str, Semaphore] = {}

def _get_sem_for(api_key: str) -> Optional[Semaphore]:
    """
    Return a semaphore for this api_key if concurrency limiting is enabled.
    Creates on first use, caches thereafter. Returns None if disabled.
    """
    max_conc = OPENAI_MAX_CONCURRENCY_PER_KEY
    if max_conc <= 0:
        return None
    with _sem_lock:
        sem = _sems.get(api_key)
        if sem is None:
            sem = Semaphore(max_conc)
            _sems[api_key] = sem
        return sem

# -------------------------- Public Gateway Function ---------------------------

def call_openai_rate_limited(
    api_key: str,
    model: str,
    prompt_text: str,
    max_output_tokens: Optional[int],
    temperature_zero: bool,
) -> Dict[str, Any]:
    """
    The ONLY function the rest of the codebase should use to talk to OpenAI.

    Behavior:
      - If concurrency limiting is enabled (>0), blocks on a per-key semaphore
        until an in-flight slot is available.
      - Applies per-key RPM via pyrate-limiter (3.9.0):
          * OPENAI_RPM_FAIL_FAST = False (default): blocks until token is free.
          * OPENAI_RPM_FAIL_FAST = True: raises OpenAIRateLimitError (HTTP 429).
      - Calls the low-level client (app.core.openai_client.call_openai_api).

    Returns:
      - The dict response from the low-level client.

    Raises:
      - OpenAIRateLimitError (HTTP 429) when RPM exceeds and fail-fast is on.
      - Whatever the low-level client raises (wrap/catch in handlers as needed).
    """
    sem = _get_sem_for(api_key)
    if sem is not None:
        sem.acquire()  # blocks until a free in-flight slot

    try:
        try:
            # pyrate-limiter 3.9.0:
            #   limiter.ratelimit(identity, delay=True|False)
            #   - delay=True  -> block/pause until a token is available
            #   - delay=False -> raise BucketFullException immediately
            with _limiter.ratelimit(api_key, delay=not OPENAI_RPM_FAIL_FAST):
                # Local import to avoid circular imports at startup
                from app.core.openai_client import call_openai_api
                return call_openai_api(api_key, model, prompt_text, max_output_tokens, temperature_zero)

        except BucketFullException as e:
            # Convert pyrate-limiter exception into a clean HTTP 429
            reset_in: Optional[float] = None
            # pyrate-limiter 3.9.0 exposes meta_info; be defensive
            try:
                meta = getattr(e, "meta_info", {}) or {}
                # meta may include 'reset_in' seconds
                if "reset_in" in meta:
                    reset_in = float(meta["reset_in"])
            except Exception:
                pass

            detail = (
                f"OpenAI RPM limit exceeded for API key. "
                f"Configured limit: {OPENAI_RPM_PER_KEY}/minute."
            )
            raise OpenAIRateLimitError(detail=detail, retry_after=reset_in)

    finally:
        if sem is not None:
            sem.release()

# -------------------------- Testing / DI Hooks --------------------------------

def set_test_impl(fake_fn) -> None:
    """
    Allows tests to swap the gateway implementation, e.g.:

        def fake_call(api_key, model, prompt_text, max_output_tokens, temperature_zero):
            return {"status": "completed", "content": "..."}
        set_test_impl(fake_call)
    """
    global call_openai_rate_limited
    call_openai_rate_limited = fake_fn  # type: ignore[assignment]
