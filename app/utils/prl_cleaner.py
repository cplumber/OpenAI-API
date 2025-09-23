# app/utils/prl_cleaner.py
from __future__ import annotations
import os, shutil, threading, time
from pathlib import Path
from typing import List
import logging

from app.config import DEBUG_REQUEST_LOG_DIR, DEBUG_REQUEST_LOG_ENABLED

# Configurable caps (read from config.py)
try:
    from app.config import PRL_MAX_BYTES
except Exception:
    PRL_MAX_BYTES = 10 * 1024 * 1024  # 100 MB

try:
    from app.config import PRL_CLEAN_INTERVAL_SEC
except Exception:
    PRL_CLEAN_INTERVAL_SEC = 3600      # 1 hour

log = logging.getLogger(__name__)

def _dir_size_bytes(p: Path) -> int:
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except Exception:
                pass
    return total

def _list_request_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return [d for d in root.iterdir() if d.is_dir()]

def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except Exception:
        return 0.0

def prune_once() -> int:
    """
    Delete the oldest request directories first until total size of DEBUG_REQUEST_LOG_DIR
    is <= PRL_MAX_BYTES. Returns number of deleted directories.
    """
    base = Path(DEBUG_REQUEST_LOG_DIR).resolve()
    if not base.exists():
        return 0

    def total_size():
        return _dir_size_bytes(base)

    deleted = 0
    dirs = sorted(_list_request_dirs(base), key=_mtime, reverse=True)

    if total_size() <= PRL_MAX_BYTES:
        return 0

    for d in reversed(dirs):  # start with oldest
        try:
            shutil.rmtree(d, ignore_errors=True)
            deleted += 1
            if total_size() <= PRL_MAX_BYTES:
                break
        except Exception:
            pass

    return deleted

def _loop():
    while True:
        try:
            deleted = prune_once()
            if deleted:
                log.info("PRL cleanup: deleted %d old request directories", deleted)
        except Exception as e:
            log.exception("PRL cleanup error: %s", e)
        time.sleep(PRL_CLEAN_INTERVAL_SEC)

_started = False
def start_prl_cleanup_scheduler() -> None:
    """
    Run a one-time cleanup immediately, then start a background thread
    to enforce PRL_MAX_BYTES every PRL_CLEAN_INTERVAL_SEC.
    Does nothing if DEBUG_REQUEST_LOG_ENABLED = False.
    """
    global _started
    if _started or not DEBUG_REQUEST_LOG_ENABLED:
        return
    # one-time cleanup at startup
    try:
        deleted = prune_once()
        if deleted:
            log.info("PRL startup cleanup: deleted %d old request directories", deleted)
    except Exception as e:
        log.exception("PRL startup cleanup error: %s", e)

    # background thread
    t = threading.Thread(target=_loop, name="prl-cleaner", daemon=True)
    t.start()
    _started = True
