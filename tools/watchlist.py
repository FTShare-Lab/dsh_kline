"""Persistent, user-local watchlist state shared by dsh_kline clients.

Charts, conversations and sidebar tabs deliberately have different local
state.  A watchlist is different: it is a user collection and must survive
switching conversations or restarting an individual MCP process.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


MAX_ITEMS = 48
MAX_GROUPS = 12
_LOCK = threading.RLock()
_MILLISECONDS_THRESHOLD = 100_000_000_000


def _state_path() -> Path:
    configured = str(os.environ.get("DSH_KLINE_STATE_DIR") or "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".cache" / "dsh_kline"
    return root / "watchlist-v1.json"


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "revision": 0,
        "updated_at": 0,
        "groups": [{"id": "default", "name": "默认分组"}],
        "items": [],
        "activeGroupId": "default",
        "sort": "manual",
    }


def _normalize_state(value: Any) -> dict[str, Any]:
    base = _default_state()
    if not isinstance(value, dict):
        return base
    groups: list[dict[str, str]] = []
    seen_groups: set[str] = set()
    for raw in value.get("groups") if isinstance(value.get("groups"), list) else []:
        if not isinstance(raw, dict):
            continue
        group_id = str(raw.get("id") or "").strip()[:48]
        name = str(raw.get("name") or "").strip()[:24]
        if not group_id or not name or group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        groups.append({"id": group_id, "name": name})
        if len(groups) >= MAX_GROUPS:
            break
    if "default" not in seen_groups:
        groups.insert(0, {"id": "default", "name": "默认分组"})
        groups = groups[:MAX_GROUPS]
    allowed = {group["id"] for group in groups}
    items: list[dict[str, str]] = []
    seen_items: set[tuple[str, str]] = set()
    for raw in value.get("items") if isinstance(value.get("items"), list) else []:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()[:64]
        name = str(raw.get("name") or symbol).strip()[:80]
        group_id = str(raw.get("groupId") or raw.get("group_id") or "default").strip()[:48]
        key = (symbol, group_id)
        if not symbol or group_id not in allowed or key in seen_items:
            continue
        seen_items.add(key)
        items.append({"symbol": symbol, "name": name or symbol, "groupId": group_id})
        if len(items) >= MAX_ITEMS:
            break
    active = str(value.get("activeGroupId") or value.get("active_group_id") or "default")
    if active not in allowed:
        active = "default"
    updated_at = max(0, int(value.get("updated_at") or 0))
    # Early development builds wrote seconds.  Persist milliseconds from now
    # on so client edits made in the same second remain orderable.
    if 0 < updated_at < _MILLISECONDS_THRESHOLD:
        updated_at *= 1000
    return {
        "version": 1,
        "revision": max(0, int(value.get("revision") or 0)),
        "updated_at": updated_at,
        "groups": groups,
        "items": items,
        "activeGroupId": active,
        "sort": value.get("sort") if value.get("sort") in {"manual", "change_desc", "change_asc"} else "manual",
    }


def get_watchlist_state() -> dict[str, Any]:
    """Read the user-local watchlist; missing/corrupt files safely become empty."""
    with _LOCK:
        try:
            raw = json.loads(_state_path().read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            raw = None
        return _normalize_state(raw)


def save_watchlist_state(state: Any) -> dict[str, Any]:
    """Atomically persist a complete validated user watchlist and return it.

    A browser sends the revision it last read.  Rejecting a stale write gives
    it a chance to reconcile instead of silently overwriting edits made in a
    different conversation or DSH instance.
    """
    with _LOCK:
        previous = get_watchlist_state()
        expected_revision: int | None = None
        if isinstance(state, dict) and "revision" in state:
            try:
                expected_revision = max(0, int(state.get("revision")))
            except (TypeError, ValueError):
                return {"ok": False, "error": "watchlist_invalid_revision", "message": "自选版本号无效"}
        if expected_revision is not None and expected_revision != previous["revision"]:
            return {
                "ok": False,
                "error": "watchlist_conflict",
                "message": "自选已在另一处更新，请同步后重试",
                "watchlist": previous,
            }
        normalized = _normalize_state(state)
        normalized["revision"] = previous["revision"] + 1
        normalized["updated_at"] = time.time_ns() // 1_000_000
        path = _state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix="watchlist-", suffix=".tmp", dir=path.parent)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(normalized, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
        except OSError as exc:
            try:
                os.unlink(temporary_name)
            except (OSError, UnboundLocalError):
                pass
            return {"ok": False, "error": "watchlist_persist_failed", "message": f"无法保存自选：{exc}"}
        return {"ok": True, "watchlist": normalized}
