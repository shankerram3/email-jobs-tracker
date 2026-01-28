"""In-memory sync progress state (read by GET /api/sync-status)."""
import threading

_state = {
    "status": "idle",  # idle | syncing
    "message": "",
    "processed": 0,
    "total": 0,
    "created": 0,
    "skipped": 0,
    "errors": 0,
    "error": None,
}
_lock = threading.Lock()


def get_state():
    with _lock:
        return dict(_state)


def set_syncing(total=0):
    with _lock:
        _state["status"] = "syncing"
        _state["message"] = "Connecting to Gmail…" if total == 0 else "Processing…"
        _state["processed"] = 0
        _state["total"] = total
        _state["created"] = 0
        _state["skipped"] = 0
        _state["errors"] = 0
        _state["error"] = None


def update_progress(processed: int, total: int, message: str = "Classifying…"):
    with _lock:
        _state["processed"] = processed
        _state["total"] = total
        _state["message"] = message


def set_idle(result: dict):
    with _lock:
        _state["status"] = "idle"
        _state["message"] = "Done"
        _state["processed"] = result.get("processed", 0)
        _state["total"] = result.get("processed", 0)
        _state["created"] = result.get("created", 0)
        _state["skipped"] = result.get("skipped", 0)
        _state["errors"] = result.get("errors", 0)
        _state["error"] = result.get("error")


def set_error(err: str):
    with _lock:
        _state["status"] = "idle"
        _state["error"] = err
        _state["message"] = ""
