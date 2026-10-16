"""Whitelisted browser object observations; never upgrade them to pixel verification."""
from __future__ import annotations

KINDS = {"horizontal_line", "trend_line", "channel", "rectangle"}
REASONS = {
    "created": {"overlay_registered", "outside_time_viewport"},
    "hidden": {"period_mismatch", "anchors_not_loaded"},
    "removed": {"overlay_removed"},
    "failed": {"invalid_geometry", "overlay_missing", "overlay_mismatch", "overlay_still_present", "creation_failed"},
    "unknown": {"overlay_api_unavailable", "overlay_lookup_failed", "overlay_mismatch", "context_not_ready", "application_rolled_back", "rollback_unknown"},
}


def _empty(status):
    return {"schema_version": 1, "report_status": status, "evidence_scope": "chart_object_api",
            "render_verified": False, "pixel_verified": False, "items": []}


def sanitize_drawing_feedback(raw, allowed):
    if raw is None: return _empty("not_reported")
    if isinstance(raw, dict) and isinstance(raw.get("report_status"), str) and raw["report_status"] in {"not_reported", "invalid"}:
        return _empty(raw["report_status"])
    try:
        if (not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1
            or raw.get("phase") not in {"current", "applied", "rolled_back", "rollback_unknown"}
            or not isinstance(raw.get("items"), list) or len(raw["items"]) > 360): raise ValueError("report")
        objects = {d["id"]: d["kind"] for d in allowed}; seen = set(); items = []
        for item in raw["items"]:
            identity, kind, status, reason, visibility = (item[k] for k in ("id", "kind", "status", "reason", "visibility"))
            if (not isinstance(identity, str) or not 1 <= len(identity) <= 256 or identity in seen or objects.get(identity) != kind
                or kind not in KINDS or status not in REASONS or reason not in REASONS[status]
                or visibility not in {"unknown", "outside_time_viewport", "not_applicable"}
                or (reason == "outside_time_viewport") != (visibility == "outside_time_viewport")): raise ValueError("item")
            seen.add(identity)
            items.append({"id": identity, "kind": kind, "status": status, "reason": reason, "visibility": visibility,
                          "outside_loaded_price_envelope": item.get("outside_loaded_price_envelope") is True})
        if len(seen) != len(objects): raise ValueError("coverage")
        return {**_empty("reported"), "phase": raw["phase"], "items": items}
    except (ValueError, TypeError, KeyError, AttributeError): return _empty("invalid")
