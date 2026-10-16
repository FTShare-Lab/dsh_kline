/** Diagnostic only: never an edit capability, alignment bypass or rendering receipt. */
export declare const SOURCE_STATUS_REASONS: {
    readonly not_checked: readonly ["not_checked", "retry_observation"];
    readonly chart_not_ready: readonly ["not_checked", "wait_for_chart"];
    readonly client_unsupported: readonly ["blocked", "reload_client"];
    readonly view_inactive: readonly ["blocked", "activate_view"];
    readonly ambiguous_views: readonly ["blocked", "keep_one_active_view"];
    readonly source_missing: readonly ["blocked", "reopen_chart"];
    readonly source_unavailable: readonly ["blocked", "reopen_chart"];
    readonly source_owner_mismatch: readonly ["blocked", "reopen_chart"];
    readonly source_unconfirmed: readonly ["blocked", "check_drawing_status"];
    readonly source_metadata_unknown: readonly ["blocked", "check_chart_settings"];
    readonly source_limit_exceeded: readonly ["blocked", "reduce_range"];
    readonly drawing_pending: readonly ["checking", "check_drawing_status"];
    readonly drawing_outcome_unknown: readonly ["blocked", "check_drawing_status"];
    readonly source_snapshot_mismatch: readonly ["blocked", "retry_observation"];
    readonly source_payload_invalid: readonly ["blocked", "retry_observation"];
    readonly source_handoff_pending: readonly ["checking", "wait_for_report"];
    readonly source_handoff_rejected: readonly ["blocked", "retry_observation"];
    readonly source_matches_view: readonly ["aligned", "continue_guarded_workflow"];
    readonly context_transport_unavailable: readonly ["blocked", "retry_observation"];
    readonly source_handoff_unavailable: readonly ["blocked", "retry_observation"];
};
export declare function sourceStatus(reason?: keyof typeof SOURCE_STATUS_REASONS): {
    schema_version: number;
    scope: string;
    phase: "not_checked" | "blocked" | "checking" | "aligned";
    reason: "not_checked" | "chart_not_ready" | "client_unsupported" | "view_inactive" | "ambiguous_views" | "source_missing" | "source_unavailable" | "source_owner_mismatch" | "source_unconfirmed" | "source_metadata_unknown" | "source_limit_exceeded" | "drawing_pending" | "drawing_outcome_unknown" | "source_snapshot_mismatch" | "source_payload_invalid" | "source_handoff_pending" | "source_handoff_rejected" | "source_matches_view" | "context_transport_unavailable" | "source_handoff_unavailable";
    next_action: "retry_observation" | "wait_for_chart" | "reload_client" | "activate_view" | "keep_one_active_view" | "reopen_chart" | "check_drawing_status" | "check_chart_settings" | "reduce_range" | "wait_for_report" | "continue_guarded_workflow";
    edit_authorized: boolean;
};
export declare function sanitizeSourceStatus(raw: any): {
    schema_version: number;
    scope: string;
    phase: "not_checked" | "blocked" | "checking" | "aligned";
    reason: "not_checked" | "chart_not_ready" | "client_unsupported" | "view_inactive" | "ambiguous_views" | "source_missing" | "source_unavailable" | "source_owner_mismatch" | "source_unconfirmed" | "source_metadata_unknown" | "source_limit_exceeded" | "drawing_pending" | "drawing_outcome_unknown" | "source_snapshot_mismatch" | "source_payload_invalid" | "source_handoff_pending" | "source_handoff_rejected" | "source_matches_view" | "context_transport_unavailable" | "source_handoff_unavailable";
    next_action: "retry_observation" | "wait_for_chart" | "reload_client" | "activate_view" | "keep_one_active_view" | "reopen_chart" | "check_drawing_status" | "check_chart_settings" | "reduce_range" | "wait_for_report" | "continue_guarded_workflow";
    edit_authorized: boolean;
};
export declare function sourceFailure(error: any): {
    schema_version: number;
    scope: string;
    phase: "not_checked" | "blocked" | "checking" | "aligned";
    reason: "not_checked" | "chart_not_ready" | "client_unsupported" | "view_inactive" | "ambiguous_views" | "source_missing" | "source_unavailable" | "source_owner_mismatch" | "source_unconfirmed" | "source_metadata_unknown" | "source_limit_exceeded" | "drawing_pending" | "drawing_outcome_unknown" | "source_snapshot_mismatch" | "source_payload_invalid" | "source_handoff_pending" | "source_handoff_rejected" | "source_matches_view" | "context_transport_unavailable" | "source_handoff_unavailable";
    next_action: "retry_observation" | "wait_for_chart" | "reload_client" | "activate_view" | "keep_one_active_view" | "reopen_chart" | "check_drawing_status" | "check_chart_settings" | "reduce_range" | "wait_for_report" | "continue_guarded_workflow";
    edit_authorized: boolean;
};
