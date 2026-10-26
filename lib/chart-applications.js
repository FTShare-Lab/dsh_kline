/** Single-delivery applications. Only a matching live-view state can confirm a candidate. */
import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { drawingInventory, observationKey } from "./chart-observation.js";
import { sanitizeDrawingFeedback } from "./drawing-feedback.js";
const TOKEN = /^[A-Za-z0-9_-]{32}$/;
const TERMINAL = new Set(['applied', 'rejected', 'failed', 'outcome_unknown']);
export class ChartApplications {
    runtime;
    now;
    constructor(runtime, now = () => Date.now()) { this.runtime = runtime; this.now = now; }
    directory(ref) { if (!TOKEN.test(ref))
        throw Error('invalid_apply_ref'); return join(this.runtime, 'edits', String(process.pid), ref); }
    path(ref, token) { if (!TOKEN.test(token))
        throw Error('invalid_apply_token'); return join(this.directory(ref), 'applications', token + '.json'); }
    async read(path) {
        const content = await readFile(path, 'utf8');
        if (content.length > 8 * 1024 * 1024)
            throw Error('invalid_apply_record');
        return JSON.parse(content);
    }
    async write(path, value) {
        await mkdir(join(path, '..'), { recursive: true, mode: 0o700 });
        const temporary = path + '.' + randomBytes(8).toString('hex') + '.tmp';
        await writeFile(temporary, JSON.stringify(value), { mode: 0o600, flag: 'wx' });
        await rename(temporary, path);
    }
    recoveryPath(conversation) {
        if (typeof conversation !== 'string' || !conversation || conversation.length > 1024)
            throw Error('invalid_recovery_owner');
        return join(this.runtime, 'recoveries', String(process.pid), createHash('sha256').update(conversation).digest('hex') + '.json');
    }
    async recover(conversation) {
        // A recovery checkpoint is an explicitly confirmed historical chart, not
        // a fallback current-view observation or a globally latest publication.
        const checkpoint = await this.read(this.recoveryPath(conversation));
        if (checkpoint.host_process_id !== process.pid || checkpoint.conversation_id !== conversation
            || !TOKEN.test(checkpoint.candidate_chart_session) || !TOKEN.test(checkpoint.context_ref))
            throw Error('invalid_recovery_checkpoint');
        const app = await this.read(this.path(checkpoint.context_ref, checkpoint.candidate_chart_session));
        if (app.status !== 'applied' || app.confirmed_chart_session !== checkpoint.candidate_chart_session
            || app.host_process_id !== process.pid || app.conversation_id !== conversation || app.context_ref !== checkpoint.context_ref)
            throw Error('unconfirmed_recovery');
        const candidate = await this.candidate(app);
        const ancestors = [], seen = new Set([checkpoint.candidate_chart_session]);
        let parent = candidate.drawing_parent_session;
        while (parent) {
            if (!TOKEN.test(parent) || seen.has(parent) || ancestors.length >= 64)
                throw Error('invalid_recovery_lineage');
            seen.add(parent);
            ancestors.push(parent);
            const saved = await this.read(join(this.runtime, 'sessions', parent + '.json'));
            if (saved.ok !== true || saved.session !== parent || saved.host_process_id !== process.pid)
                throw Error('invalid_recovery_lineage');
            const guard = saved.payload?.drawing_guard || saved.payload?.view_source_guard;
            if (!guard)
                break;
            if (guard.conversation_id !== conversation)
                throw Error('invalid_recovery_lineage');
            parent = saved.payload.drawing_parent_session;
        }
        const { drawing_guard, ...payload } = candidate;
        return { ok: true, session: checkpoint.candidate_chart_session, recovery: true, conversation_id: conversation,
            symbol: payload.symbol, name: payload.name, published_at: app.acknowledged_at_ms,
            recovery_scope: 'confirmed_historical_chart', render_verified: false,
            recovery_source_sessions: ancestors,
            payload: { ...payload, _live_chart_session: checkpoint.candidate_chart_session, _live_application_pending: false } };
    }
    validate(app, view, token) {
        if (app.host_process_id !== process.pid || app.context_ref !== view.ref || app.candidate_chart_session !== token
            || app.conversation_id !== view.conversation || app.view_id !== view.view)
            throw Error('invalid_apply_owner');
    }
    async candidate(app) {
        const saved = await this.read(join(this.runtime, 'sessions', app.candidate_chart_session + '.json'));
        const guard = saved.payload?.drawing_guard;
        if (saved.host_process_id !== process.pid || saved.session !== app.candidate_chart_session || saved.ok !== true
            || guard?.protocol !== 'prepared-only-v1' || guard.context_ref !== app.context_ref || guard.view_id !== app.view_id
            || guard.conversation_id !== app.conversation_id || guard.expected_revision !== app.expected_revision
            || guard.request_id !== app.request_id)
            throw Error('invalid_apply_candidate');
        return saved.payload;
    }
    publicReceipt(app) {
        return { candidate_chart_session: app.candidate_chart_session, lease_id: app.lease_id, apply_status: app.status,
            confirmed_chart_session: app.confirmed_chart_session ?? null, render_verified: false, confirmation_scope: app.status === 'applied' ? 'view_state_only' : 'not_confirmed',
            drawing_feedback: app.drawing_feedback ?? sanitizeDrawingFeedback(null, []) };
    }
    async acknowledge(view, receipt) {
        const token = receipt?.candidate_chart_session, lease = receipt?.lease_id;
        if (typeof token !== 'string' || !TOKEN.test(token) || typeof lease !== 'string' || !TOKEN.test(lease)
            || !['applied', 'rejected', 'failed', 'outcome_unknown'].includes(receipt.status))
            throw Error('invalid_apply_receipt');
        const path = this.path(view.ref, token), app = await this.read(path);
        this.validate(app, view, token);
        if (app.lease_id !== lease || !['delivered', 'applied', 'rejected', 'failed', 'outcome_unknown'].includes(app.status))
            throw Error('invalid_apply_lease');
        if (TERMINAL.has(app.status) && (app.status !== 'outcome_unknown' || app.acknowledged_at_ms !== undefined))
            return this.publicReceipt(app);
        const payload = await this.candidate(app);
        const allowed = [...new Map([...app.base_state.drawings.filter((d) => d.origin === 'ai'), ...drawingInventory(payload)].map((d) => [d.id, d])).values()];
        app.drawing_feedback = sanitizeDrawingFeedback(receipt.drawing_feedback, allowed);
        if (receipt.status === 'applied') {
            const expected = { ...app.base_state, source_chart_session: token,
                drawings: [...app.base_state.drawings.filter((d) => d.origin !== 'ai'), ...drawingInventory(payload)] };
            if (observationKey(view.state) !== observationKey(expected)) {
                app.status = 'outcome_unknown';
                app.reason = 'ack_state_mismatch';
            }
            else {
                app.status = 'applied';
                app.confirmed_chart_session = token;
                app.reason = 'state_confirmed';
            }
        }
        else {
            app.status = receipt.status;
            app.reason = ['local_state_changed', 'inactive', 'apply_failed', 'rollback_failed', 'invalid_delivery'].includes(receipt.reason)
                ? receipt.reason : 'view_reported_failure';
        }
        app.acknowledged_at_ms = this.now();
        await this.write(path, app);
        if (app.status === 'applied') {
            // Only a new successful receipt advances the per-conversation pointer.
            // A duplicate historical receipt cannot roll it back to an older chart.
            try {
                await this.write(this.recoveryPath(view.conversation), { host_process_id: process.pid, conversation_id: view.conversation,
                    context_ref: view.ref, candidate_chart_session: token });
            }
            catch { }
        }
        return { ...this.publicReceipt(app), new_receipt: true };
    }
    async dispatch(view) {
        let index;
        try {
            index = await this.read(join(this.directory(view.ref), 'pending.json'));
        }
        catch (error) {
            if (error?.code === 'ENOENT')
                return undefined;
            throw error;
        }
        const token = index.candidate_chart_session, path = this.path(view.ref, token), app = await this.read(path);
        this.validate(app, view, token);
        if (!Number.isSafeInteger(app.expires_at_ms))
            throw Error('invalid_apply_deadline');
        if (this.now() > app.expires_at_ms && ['queued', 'delivered'].includes(app.status)) {
            app.status = app.status === 'queued' ? 'rejected' : 'outcome_unknown';
            app.reason = 'delivery_expired';
            await this.write(path, app);
        }
        if (app.status !== 'queued')
            return undefined; // Never resend a delivery whose reply may have been lost.
        if (view.applyCapable !== true || !view.active || view.ambiguous || view.revision !== app.expected_revision || observationKey(view.state) !== observationKey(app.base_state)) {
            app.status = 'rejected';
            app.reason = 'dispatch_state_changed';
            await this.write(path, app);
            return undefined;
        }
        const payload = await this.candidate(app);
        app.status = 'delivered';
        app.lease_id = randomBytes(24).toString('base64url');
        app.delivered_at_ms = this.now();
        await this.write(path, app); // Record delivery before sending it to a browser.
        return { candidate_chart_session: token, context_ref: view.ref, conversation_id: view.conversation, view_id: view.view,
            expected_revision: view.revision, lease_id: app.lease_id, expires_at_ms: app.expires_at_ms, base_state: app.base_state,
            payload: { symbol: payload.symbol, interval: payload.interval, chartCommands: payload.chartCommands.filter((c) => ['DRAW_HORIZONTAL_LINE', 'DRAW_AGENT_TREND_LINE', 'DRAW_AGENT_CHANNEL', 'DRAW_AGENT_RECTANGLE', 'DRAW_AGENT_FIBONACCI', 'DRAW_AGENT_POLYLINE', 'DRAW_AGENT_ANNOTATION', 'DRAW_AGENT_SERIES_LINE', 'DRAW_AGENT_PRICE_BAND', 'DRAW_AGENT_PRICE_STICKS'].includes(c.type)) } };
    }
}
