import os
import sys
import types
import importlib.util
import pytest
from pathlib import Path
from contextlib import contextmanager

# ---------- Resolve ai_gateway.py ----------
def _find_ai_gateway_path() -> str:
    p = os.environ.get("AI_GATEWAY_PATH")
    if p and Path(p).is_file():
        return p
    here = Path(__file__).resolve()
    root = here.parent.parent  # project root
    for c in [root / "ai_gateway.py", root / "app" / "core" / "ai_gateway.py"]:
        if c.is_file():
            return str(c)
    # Optional fallback for sandbox; OK if missing on your machine
    if Path("/mnt/data/ai_gateway.py").is_file():
        return "/mnt/data/ai_gateway.py"
    raise FileNotFoundError("Could not find ai_gateway.py. Set AI_GATEWAY_PATH or place it at repo root.")

AI_GATEWAY_PATH = _find_ai_gateway_path()

# ---------- Package helpers ----------
def _ensure_pkg(path: str) -> None:
    parts = path.split(".")
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            if i < len(parts):
                mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = mod

def _purge_module(name: str) -> None:
    for k in list(sys.modules.keys()):
        if k == name or k.startswith(name + "."):
            sys.modules.pop(k, None)

# ---------- Pre-inject pyrate_limiter shim (avoids ImportError on import) ----------
def _ensure_pyrate_limiter_compat():
    """
    Inject a shim if 'pyrate_limiter' is missing or lacks:
    Duration, RequestRate, Limiter, MemoryListBucket, BucketFullException.
    Limiter exposes try_acquire() and a no-op ratelimit() CM.
    """
    try:
        import pyrate_limiter as _pl  # noqa
        ok = all(hasattr(_pl, n) for n in
                 ("Duration", "RequestRate", "Limiter", "MemoryListBucket", "BucketFullException"))
        if ok:
            return
    except Exception:
        pass

    pl = types.ModuleType("pyrate_limiter")

    class BucketFullException(Exception):
        def __init__(self, *args, **kwargs):
            super().__init__(*(args or ("bucket full",)))
            # tests may set .meta_info externally

    class Duration:
        SECOND = 1
        MINUTE = 60
        HOUR = 3600

    class RequestRate:
        def __init__(self, num: int, interval: int):
            self.num = num
            self.interval = interval

    class MemoryListBucket:
        pass

    class Limiter:
        def __init__(self, rate, bucket_class=None, bucket_kwargs=None):
            self.rate = rate
            self.bucket_class = bucket_class
            self.bucket_kwargs = bucket_kwargs or {}
            self.calls = 0

        def try_acquire(self, key, tokens: int = 1) -> bool:
            self.calls += 1
            return True  # tests monkeypatch _limiter

        @contextmanager
        def ratelimit(self, key, delay=True):
            yield

    pl.BucketFullException = BucketFullException
    pl.Duration = Duration
    pl.RequestRate = RequestRate
    pl.MemoryListBucket = MemoryListBucket
    pl.Limiter = Limiter

    sys.modules["pyrate_limiter"] = pl

# Ensure shim is present BEFORE tests import anything from pyrate_limiter
_ensure_pyrate_limiter_compat()

# ---------- Pytest fixtures ----------
@pytest.fixture
def inject_fake_openai_client():
    def _inject(fn):
        _ensure_pkg("app")
        _ensure_pkg("app.core")
        fake_mod = types.ModuleType("app.core.openai_client")
        fake_mod.call_openai_api = fn
        sys.modules["app.core.openai_client"] = fake_mod
    return _inject

@pytest.fixture
def reload_ai_gateway():
    def _reload(with_config: bool,
                env_overrides: dict | None = None,
                config_values: dict | None = None):
        _purge_module("app.config")
        _purge_module("app.core.ai_gateway")

        env_overrides = env_overrides or {}
        old_env = {k: os.environ.get(k) for k in env_overrides}
        try:
            for k, v in env_overrides.items():
                os.environ[k] = str(v)

            if with_config:
                _ensure_pkg("app")
                cfg = types.ModuleType("app.config")
                cv = config_values or {}
                setattr(cfg, "OPENAI_RPM_PER_KEY", int(cv.get("OPENAI_RPM_PER_KEY", 480)))
                setattr(cfg, "OPENAI_RPM_FAIL_FAST", bool(cv.get("OPENAI_RPM_FAIL_FAST", False)))
                setattr(cfg, "OPENAI_MAX_CONCURRENCY_PER_KEY", int(cv.get("OPENAI_MAX_CONCURRENCY_PER_KEY", 20)))
                setattr(cfg, "OPENAI_RPM_MAX_DELAY_MS", int(cv.get("OPENAI_RPM_MAX_DELAY_MS", 0)))
                setattr(cfg, "OPENAI_REDIS_URL", str(cv.get("OPENAI_REDIS_URL", "")))
                sys.modules["app.config"] = cfg
            else:
                if "app.config" in sys.modules:
                    del sys.modules["app.config"]

            _ensure_pkg("app"); _ensure_pkg("app.core")
            spec = importlib.util.spec_from_file_location("app.core.ai_gateway", AI_GATEWAY_PATH)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load spec for {AI_GATEWAY_PATH}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["app.core.ai_gateway"] = mod
            spec.loader.exec_module(mod)  # type: ignore[arg-type]
            return mod
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _reload

@pytest.fixture(autouse=True)
def _clear_ai_gateway_semaphores():
    try:
        import app.core.ai_gateway as mod
        if hasattr(mod, "_sem_lock") and hasattr(mod, "_sems"):
            with mod._sem_lock:
                mod._sems.clear()
    except Exception:
        pass
    yield
    try:
        import app.core.ai_gateway as mod
        if hasattr(mod, "_sem_lock") and hasattr(mod, "_sems"):
            with mod._sem_lock:
                mod._sems.clear()
    except Exception:
        pass
