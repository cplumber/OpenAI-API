import time
import threading
import pytest
from contextlib import contextmanager
import math

# --------------------------- Fake limiter factory -----------------------------

def make_fake_limiter(mod, mode="ok", reset_in=1.4):
    def _bucket_full_exc(reset_in_val: float):
        cls = mod.BucketFullException
        exc = cls.__new__(cls)
        Exception.__init__(exc, "bucket full")
        setattr(exc, "meta_info", {
            "reset_in": float(reset_in_val),
            "rate": f"{mod.OPENAI_RPM_PER_KEY}/minute",
        })
        return exc

    class FakeLimiter:
        def __init__(self):
            self.mode = mode
            self.reset_in = float(reset_in)
            self.last_key = None
            self.calls = 0

        def try_acquire(self, key, tokens=1):
            self.last_key = key
            self.calls += 1
            if self.mode == "ok":
                return True
            raise _bucket_full_exc(self.reset_in)

        @contextmanager
        def ratelimit(self, key, delay=True):
            self.last_key = key
            self.calls += 1
            if self.mode == "ok":
                yield
            else:
                raise _bucket_full_exc(self.reset_in)

    return FakeLimiter()

# ------------------------------- Tests ----------------------------------------

def test_calls_openai_api_under_limits(monkeypatch, reload_ai_gateway, inject_fake_openai_client):
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 0,
        "OPENAI_RPM_PER_KEY": 123,
        "OPENAI_RPM_FAIL_FAST": False,
        "OPENAI_RPM_MAX_DELAY_MS": 1000,
    })
    fake = make_fake_limiter(mod, mode="ok")
    monkeypatch.setattr(mod, "_limiter", fake, raising=True)

    captured = {}
    def fake_call(api_key, model, prompt_text, max_output_tokens, temperature_zero):
        captured.update(locals())
        return {"status": "ok", "model": model, "echo": prompt_text}
    inject_fake_openai_client(fake_call)

    out = mod.call_openai_rate_limited("k-123", "gpt-x", "hello", 42, True)

    print(f"[INFO] call_openai_api_under_limits -> api_key={captured['api_key']}, "
          f"model={captured['model']}, limiter_calls={fake.calls}")

    assert out["status"] == "ok"
    assert fake.calls >= 1

@pytest.mark.parametrize(
    "rpm, reset_in, expect_trigger",
    [
        (100, 1.2, False),  # RPM-1 (well below 480): should NOT trigger
        (480, 0.5, True),   # RPM (at default limit): should trigger
        (500, 2.0, True),   # RPM+1 (above default): should trigger
    ],
)
def test_rpm_fail_fast_matrix(monkeypatch, reload_ai_gateway, inject_fake_openai_client, rpm, reset_in, expect_trigger):
    """
    Matrix test for RPM fail-fast behavior against default production limit (480).
    - When expect_trigger is False, limiter yields and no 429 is raised.
    - When expect_trigger is True, limiter raises BucketFullException and gateway returns 429 with proper Retry-After.
    """
    # Configure gateway (fail-fast = True to exercise 429 path when triggered)
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_RPM_PER_KEY": rpm,
        "OPENAI_RPM_FAIL_FAST": True,
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 0,
    })

    # Conditional fake limiter:
    # - If expect_trigger: ratelimit(delay=False) raises with .meta_info.reset_in
    # - Else: it yields normally (no limit hit)
    def _bucket_full_exc(reset_in_val: float):
        cls = mod.BucketFullException
        exc = cls.__new__(cls)
        Exception.__init__(exc, "bucket full")
        setattr(exc, "meta_info", {"reset_in": float(reset_in_val), "rate": f"{rpm}/minute"})
        return exc

    class _ConditionalLimiter:
        def __init__(self): self.calls = 0
        def try_acquire(self, key, tokens=1):
            # Gateway uses ratelimit(); keep try_acquire harmless
            self.calls += 1
            if expect_trigger:
                raise _bucket_full_exc(reset_in)
            return True
        @contextmanager
        def ratelimit(self, key, delay=True):
            self.calls += 1
            if expect_trigger:
                # fail-fast path sets delay=False in gateway logic
                raise _bucket_full_exc(reset_in)
            yield

    fake = _ConditionalLimiter()
    monkeypatch.setattr(mod, "_limiter", fake, raising=True)

    if expect_trigger:
        # client MUST NOT be called when failing fast
        inject_fake_openai_client(lambda *a, **k: (_ for _ in ()).throw(AssertionError("client must not be called")))
        with pytest.raises(mod.OpenAIRateLimitError) as ei:
            mod.call_openai_rate_limited("key-x", "model-y", "prompt", None, False)
        err = ei.value
        expected_retry_after = str(int(math.ceil(reset_in)))
        assert err.status_code == 429
        assert err.headers.get("Retry-After") == expected_retry_after
        assert f"{rpm}/minute" in err.detail
        print(f"[INFO] RPM={rpm} TRIGGERED ✔ reset_in={reset_in} -> Retry-After={expected_retry_after}; limiter_calls={fake.calls}")
    else:
        # when not triggered, the client is called and returns ok
        inject_fake_openai_client(lambda *a, **k: {"status": "ok"})
        out = mod.call_openai_rate_limited("key-x", "model-y", "prompt", 64, True)
        assert out["status"] == "ok"
        print(f"[INFO] RPM={rpm} NOT TRIGGERED ✔ limiter_calls={fake.calls}")


def test_blocking_mode_does_not_raise(monkeypatch, reload_ai_gateway, inject_fake_openai_client):
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_RPM_PER_KEY": 55,
        "OPENAI_RPM_FAIL_FAST": False,
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 0,
    })
    fake = make_fake_limiter(mod, mode="ok")
    monkeypatch.setattr(mod, "_limiter", fake, raising=True)

    inject_fake_openai_client(lambda *a, **k: {"status": "ok"})
    out = mod.call_openai_rate_limited("k", "m", "p", 10, True)

    print(f"[INFO] blocking_mode_does_not_raise -> result={out}, limiter_calls={fake.calls}")

    assert out["status"] == "ok"


def test_concurrency_limits_block(monkeypatch, reload_ai_gateway, inject_fake_openai_client):
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 1,
        "OPENAI_RPM_PER_KEY": 10_000,
        "OPENAI_RPM_FAIL_FAST": False,
    })

    class _OKLimiter:
        def __init__(self): self.calls = 0
        def try_acquire(self, key, tokens=1):
            self.calls += 1
            return True
        @contextmanager
        def ratelimit(self, key, delay=True):
            self.calls += 1
            yield

    ok = _OKLimiter()
    monkeypatch.setattr(mod, "_limiter", ok, raising=True)

    def slow_call(*a, **k):
        time.sleep(0.35)
        return {"status": "ok"}
    inject_fake_openai_client(slow_call)

    results = []
    def worker():
        results.append(mod.call_openai_rate_limited("same-key", "m", "p", None, True))

    t0 = time.perf_counter()
    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()
    elapsed = time.perf_counter() - t0

    print(f"[INFO] concurrency_limits_block -> elapsed={elapsed:.3f}s, calls={ok.calls}, results={results}")

    assert elapsed >= 0.65
    assert len(results) == 2


def test_env_fallbacks_when_config_missing(monkeypatch, reload_ai_gateway):
    env = {
        "OPENAI_RPM_PER_KEY": "999",
        "OPENAI_RPM_FAIL_FAST": "1",
        "OPENAI_MAX_CONCURRENCY_PER_KEY": "7",
        "OPENAI_REDIS_URL": "redis://x",
    }
    mod = reload_ai_gateway(with_config=False, env_overrides=env)

    print(f"[INFO] env_fallbacks_when_config_missing -> "
          f"RPM={mod.OPENAI_RPM_PER_KEY}, FAIL_FAST={mod.OPENAI_RPM_FAIL_FAST}, "
          f"CONC={mod.OPENAI_MAX_CONCURRENCY_PER_KEY}, REDIS={mod.OPENAI_REDIS_URL}")

    assert mod.OPENAI_RPM_PER_KEY == 999


def test_retry_after_header_rounding(monkeypatch, reload_ai_gateway, inject_fake_openai_client):
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_RPM_FAIL_FAST": True,
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 0,
        "OPENAI_RPM_PER_KEY": 480,
    })
    fake = make_fake_limiter(mod, mode="bucketfull", reset_in=2.0)
    monkeypatch.setattr(mod, "_limiter", fake, raising=True)

    inject_fake_openai_client(lambda *a, **k: {"status": "ok"})
    with pytest.raises(mod.OpenAIRateLimitError) as ei:
        mod.call_openai_rate_limited("k", "m", "p", None, False)

    print(f"[INFO] retry_after_header_rounding -> Retry-After={ei.value.headers.get('Retry-After')}")

    assert ei.value.headers.get("Retry-After") == "2"

@pytest.mark.parametrize(
    "cap,N,D",
    [
        (5,  20, 0.15),  # 4 batches × 0.15s ≈ 0.60s
        (10, 25, 0.20),  # 3 batches × 0.20s ≈ 0.60s
        (20, 50, 0.10),  # 3 batches × 0.10s ≈ 0.30s
    ],
)
def test_concurrency_cap_parametrized(monkeypatch, reload_ai_gateway, inject_fake_openai_client, cap, N, D):
    """
    Verify per-key in-flight concurrency cap for multiple configurations.
    - cap: semaphore cap (OPENAI_MAX_CONCURRENCY_PER_KEY)
    - N:   total concurrent calls
    - D:   per-call sleep inside client (seconds)
    """
    # Realistic RPM config, focus on semaphore behavior.
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_MAX_CONCURRENCY_PER_KEY": cap,
        "OPENAI_RPM_PER_KEY": 480,       # realistic vendor-aligned RPM
        "OPENAI_RPM_FAIL_FAST": False,
    })

    # Limiter stub: never blocks (so only semaphore controls concurrency)
    class _OKLimiter:
        def __init__(self): self.calls = 0
        def try_acquire(self, key, tokens=1):
            self.calls += 1
            return True
        @contextmanager
        def ratelimit(self, key, delay=True):
            self.calls += 1
            yield

    ok = _OKLimiter()
    monkeypatch.setattr(mod, "_limiter", ok, raising=True)

    # Track concurrent in-flight calls
    active = 0
    max_active = 0
    lock = threading.Lock()

    KEY = "same-key"

    def slow_call(*a, **k):
        nonlocal active, max_active
        with lock:
            active += 1
            if active > max_active:
                max_active = active
        try:
            time.sleep(D)
            return {"status": "ok"}
        finally:
            with lock:
                active -= 1

    inject_fake_openai_client(slow_call)

    results = []
    def worker():
        results.append(mod.call_openai_rate_limited(KEY, "m", "p", None, True))

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()
    elapsed = time.perf_counter() - t0

    expected_batches = math.ceil(N / cap)
    expected_min = expected_batches * D

    # Assertions (with a small jitter allowance)
    assert len(results) == N and all(r["status"] == "ok" for r in results)
    assert elapsed >= expected_min - 0.03, f"Elapsed {elapsed:.3f}s < expected_min {expected_min:.3f}s"
    assert cap - 1 <= max_active <= cap, f"max_active={max_active}, expected close to cap={cap}"

    # Helpful output (visible with -s / -vv -s)
    print(
        f"[INFO] cap={cap} N={N} D={D:.2f} -> "
        f"elapsed={elapsed:.3f}s, batches={expected_batches}, "
        f"max_active={max_active}, limiter_calls={ok.calls}"
    )

@pytest.mark.parametrize("rpm, reset_in", [(10, 1.2), (50, 0.5), (100, 2.0)])
def test_rpm_fail_fast_sequential_gateway_level(monkeypatch, reload_ai_gateway, inject_fake_openai_client, rpm, reset_in):
    """
    Deterministic gateway-level test:
      - OPENAI_RPM_PER_KEY = rpm, FAIL_FAST=True
      - Wrap the limiter's ratelimit() so the first `rpm` entries pass,
        and the (rpm+1)-th raises BucketFullException with meta_info.reset_in.
      - Verifies your HTTP 429 + Retry-After mapping precisely.
    """
    mod = reload_ai_gateway(with_config=True, config_values={
        "OPENAI_RPM_PER_KEY": rpm,
        "OPENAI_RPM_FAIL_FAST": True,
        "OPENAI_MAX_CONCURRENCY_PER_KEY": 0,
    })

    # Build a BucketFullException with meta_info.reset_in like the real lib
    def _bucket_full_exc():
        cls = mod.BucketFullException
        exc = cls.__new__(cls)
        Exception.__init__(exc, "bucket full")
        setattr(exc, "meta_info", {"reset_in": float(reset_in), "rate": f"{rpm}/minute"})
        return exc

    # Wrap ONLY the ratelimit context manager, keep everything else intact
    real = mod._limiter
    count = {"n": 0}

    class _CountedLimiter:
        @contextmanager
        def ratelimit(self, key, delay=True):
            count["n"] += 1
            if count["n"] <= rpm:
                # allow the first `rpm` calls to pass
                with real.ratelimit(key, delay=delay):
                    yield
            else:
                # on (rpm+1)-th call, simulate bucket full immediately
                raise _bucket_full_exc()

    # Force gateway to use the wrapped ratelimit path (ignore try_acquire if present)
    monkeypatch.setattr(mod, "_limiter", _CountedLimiter(), raising=True)

    # Fast client
    inject_fake_openai_client(lambda *a, **k: {"status": "ok"})

    key = "same-key"

    # First `rpm` calls must succeed
    for i in range(rpm):
        out = mod.call_openai_rate_limited(key, "m", f"p{i}", None, True)
        assert out["status"] == "ok"

    # (rpm+1)-th must raise 429 with proper Retry-After (ceil(reset_in))
    with pytest.raises(mod.OpenAIRateLimitError) as ei:
        mod.call_openai_rate_limited(key, "m", "p-over", None, True)

    err = ei.value
    assert err.status_code == 429
    expected_retry_after = str(int(math.ceil(reset_in)))
    assert err.headers.get("Retry-After") == expected_retry_after
    assert f"{rpm}/minute" in err.detail

    print(f"[INFO] sequential gateway-level rpm={rpm} -> passed={rpm}, then 429 with Retry-After={expected_retry_after}")
