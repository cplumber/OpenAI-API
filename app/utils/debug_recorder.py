# app/utils/debug_recorder.py
from __future__ import annotations
import json, os, shutil, traceback, uuid, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

# Import explicit config (no env lookups here)
from app.config import (
    DEBUG_REQUEST_LOG_ENABLED,
    DEBUG_REQUEST_LOG_DIR,
    DEBUG_REQUEST_LOG_REDACT_KEYS,
)

DEFAULT_REDACT_KEYS = {
    "authorization","cookie","set-cookie","openai_api_key","api_key",
    "password","token","bearer","secret"
}

def _now_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]

def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-","_",".") else "_" for c in s)[:100]

def _ensure_unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suffix, i = p.stem, p.suffix, 1
    while True:
        cand = p.with_name(f"{stem}({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1

def _redacted(obj: Any, redact_keys: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if str(k).lower() in redact_keys else _redacted(v, redact_keys))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        t = type(obj)
        return t(_redacted(x, redact_keys) for x in obj)
    return obj

def _parse_extra_redact_keys(cfg_value: str) -> set[str]:
    if not cfg_value:
        return set()
    return {k.strip().lower() for k in cfg_value.split(",") if k.strip()}

class DebugRequestRecorder:
    """
    Per-request folder capturing:
      - request_meta.json
      - request_body.json (optional)
      - <field>__<original-filename>  # uploads written directly here
      - response.json  (on success)
      - exception.txt  (on error)

    Controlled *only* by app.config:
      DEBUG_REQUEST_LOG_ENABLED
      DEBUG_REQUEST_LOG_DIR
      DEBUG_REQUEST_LOG_REDACT_KEYS  (comma-separated; added to DEFAULT_REDACT_KEYS)
    """
    def __init__(self) -> None:
        self.enabled: bool = bool(DEBUG_REQUEST_LOG_ENABLED)
        self.root: Path = Path(DEBUG_REQUEST_LOG_DIR).resolve()
        self.redact_keys: set[str] = DEFAULT_REDACT_KEYS | _parse_extra_redact_keys(DEBUG_REQUEST_LOG_REDACT_KEYS)
        self.dir: Path | None = None

    def start(self, route: str, method: str, headers: Mapping[str, str], query: Mapping[str, Any] | None = None) -> "DebugRequestRecorder":
        if not self.enabled:
            return self
        rid = f"{_now_str()}_{uuid.uuid4().hex[:8]}_{_safe(route.strip('/').replace('/','_') or 'root')}"
        self.dir = self.root / rid
        self.dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "route": route,
            "method": method,
            "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "headers": _redacted({k: headers.get(k) for k in headers}, self.redact_keys),
            "query": _redacted(query or {}, self.redact_keys),
        }
        (self.dir / "request_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self

    def save_request_json(self, body: Mapping[str, Any] | None) -> None:
        if not (self.enabled and self.dir) or body is None:
            return
        (self.dir / "request_body.json").write_text(
            json.dumps(_redacted(body, self.redact_keys), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_uploads(self, uploads: Sequence[tuple[str, "UploadFileLike"]]) -> None:
        if not (self.enabled and self.dir) or not uploads:
            return
        for field, up in uploads:
            try:
                up.file.seek(0)
                fname = f"{_safe(field)}__{_safe(getattr(up, 'filename', 'upload.bin')) or 'upload.bin'}"
                dest = _ensure_unique_path(self.dir / fname)
                with open(dest, "wb") as out:
                    shutil.copyfileobj(up.file, out)
                up.file.seek(0)
            except Exception as e:
                err = self.dir / f"{_safe(field)}__WRITE_ERROR.txt"
                err.write_text(str(e), encoding="utf-8")

    def save_response(self, status_code: int, payload: Any) -> None:
        if not (self.enabled and self.dir):
            return
        out = {"status_code": status_code, "payload": _redacted(payload, self.redact_keys)}
        (self.dir / "response.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_exception(self, exc: BaseException) -> None:
        if not (self.enabled and self.dir):
            return
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        (self.dir / "exception.txt").write_text(tb, encoding="utf-8")
