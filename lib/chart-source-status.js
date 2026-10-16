/** Diagnostic only: never an edit capability, alignment bypass or rendering receipt. */
export const SOURCE_STATUS_REASONS = {
    not_checked: ['not_checked', 'retry_observation'],
    chart_not_ready: ['not_checked', 'wait_for_chart'],
    client_unsupported: ['blocked', 'reload_client'],
    view_inactive: ['blocked', 'activate_view'],
    ambiguous_views: ['blocked', 'keep_one_active_view'],
    source_missing: ['blocked', 'reopen_chart'],
    source_unavailable: ['blocked', 'reopen_chart'],
    source_owner_mismatch: ['blocked', 'reopen_chart'],
    source_unconfirmed: ['blocked', 'check_drawing_status'],
    source_metadata_unknown: ['blocked', 'check_chart_settings'],
    source_limit_exceeded: ['blocked', 'reduce_range'],
    drawing_pending: ['checking', 'check_drawing_status'],
    drawing_outcome_unknown: ['blocked', 'check_drawing_status'],
    source_snapshot_mismatch: ['blocked', 'retry_observation'],
    source_payload_invalid: ['blocked', 'retry_observation'],
    source_handoff_pending: ['checking', 'wait_for_report'],
    source_handoff_rejected: ['blocked', 'retry_observation'],
    source_matches_view: ['aligned', 'continue_guarded_workflow'],
    context_transport_unavailable: ['blocked', 'retry_observation'],
    source_handoff_unavailable: ['blocked', 'retry_observation'],
};
export function sourceStatus(reason = 'not_checked') {
    const [phase, next_action] = SOURCE_STATUS_REASONS[reason];
    return { schema_version: 1, scope: 'source_handoff', phase, reason, next_action, edit_authorized: false };
}
export function sanitizeSourceStatus(raw) {
    return sourceStatus(raw?.schema_version === 1 && typeof raw.reason === 'string'
        && Object.hasOwn(SOURCE_STATUS_REASONS, raw.reason) ? raw.reason : 'not_checked');
}
export function sourceFailure(error) {
    const message = error?.message;
    return sourceStatus(message === 'source_parent_unavailable' ? 'source_owner_mismatch'
        : message === 'unconfirmed_source_parent' ? 'source_unconfirmed'
            : error?.code === 'ENOENT' ? 'source_unavailable'
                : typeof message === 'string' && /^(?:invalid_source_|source_(?:payload|rows|inventory)_mismatch|source_ai_changed|unsupported_source_command)/.test(message)
                    ? 'source_payload_invalid' : 'source_handoff_unavailable');
}
