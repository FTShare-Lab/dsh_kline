"""Allowlisted diagnostic metadata, never edit authority or a replacement for guards."""
SOURCE_STATUS_REASONS = {
    "not_checked": ("not_checked", "retry_observation"),
    "chart_not_ready": ("not_checked", "wait_for_chart"),
    "client_unsupported": ("blocked", "reload_client"),
    "view_inactive": ("blocked", "activate_view"),
    "ambiguous_views": ("blocked", "keep_one_active_view"),
    "source_missing": ("blocked", "reopen_chart"),
    "source_unavailable": ("blocked", "reopen_chart"),
    "source_owner_mismatch": ("blocked", "reopen_chart"),
    "source_unconfirmed": ("blocked", "check_drawing_status"),
    "source_metadata_unknown": ("blocked", "check_chart_settings"),
    "source_limit_exceeded": ("blocked", "reduce_range"),
    "drawing_pending": ("checking", "check_drawing_status"),
    "drawing_outcome_unknown": ("blocked", "check_drawing_status"),
    "source_snapshot_mismatch": ("blocked", "retry_observation"),
    "source_payload_invalid": ("blocked", "retry_observation"),
    "source_handoff_pending": ("checking", "wait_for_report"),
    "source_handoff_rejected": ("blocked", "retry_observation"),
    "source_matches_view": ("aligned", "continue_guarded_workflow"),
    "context_transport_unavailable": ("blocked", "retry_observation"),
    "source_handoff_unavailable": ("blocked", "retry_observation"),
}


def sanitize_source_status(raw):
    reason = raw.get("reason") if isinstance(raw, dict) and type(raw.get("schema_version")) is int and raw["schema_version"] == 1 else None
    if not isinstance(reason, str) or reason not in SOURCE_STATUS_REASONS:
        reason = "not_checked"
    phase, action = SOURCE_STATUS_REASONS[reason]
    return {"schema_version": 1, "scope": "source_handoff", "phase": phase, "reason": reason,
            "next_action": action, "edit_authorized": False}
