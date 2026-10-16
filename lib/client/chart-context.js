/** One serial browser publisher per real view; no localStorage/history context fallback. */
import { createChartApplyController } from "./chart-apply.js";
import { observationKey } from "../chart-observation.js";
import { sourceStatus, sanitizeSourceStatus } from "../chart-source-status.js";
export const CONTEXT_PUBLICATION_TIMEOUT_MS = 8000;
export function createChartContextPublisher(options) {
    if (!options.conversationId)
        return { notify() { }, retrySource() { }, dispose() { } };
    const viewId = options.viewId ?? btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(24)))).replaceAll('+', '-').replaceAll('/', '_');
    const post = options.transport ?? (async (body, signal) => {
        const result = await fetch('/dsh-kline/context', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
        const response = await result.json();
        if (!response.ok)
            throw Error('context_publication_failed');
        return response;
    });
    const requestedTimeout = options.publicationTimeoutMs;
    const timeout = typeof requestedTimeout === 'number' && Number.isSafeInteger(requestedTimeout) && requestedTimeout > 0
        && requestedTimeout <= CONTEXT_PUBLICATION_TIMEOUT_MS ? requestedTimeout : CONTEXT_PUBLICATION_TIMEOUT_MS;
    const inFlight = new Set();
    function boundedPost(body) {
        return new Promise((resolve, reject) => {
            const controller = new AbortController();
            inFlight.add(controller);
            let settled = false;
            const finish = (done, value) => {
                if (settled)
                    return;
                settled = true;
                clearTimeout(timer);
                inFlight.delete(controller);
                controller.signal.removeEventListener('abort', onAbort);
                done(value);
            };
            const onAbort = () => finish(reject, Error('context_publication_interrupted'));
            const timer = setTimeout(() => controller.abort(), timeout);
            controller.signal.addEventListener('abort', onAbort, { once: true });
            // Consume late rejection/fulfilment, but never return a timed-out delivery
            // to the drawing controller, even if a custom transport ignores abort.
            Promise.resolve().then(() => post(body, controller.signal)).then(value => finish(resolve, value), error => finish(reject, error));
        });
    }
    let disposed = false, busy = false, pending = false, sequence = 0, lastState = '', lastActive;
    let scheduled = false;
    let lastCaptured;
    let receipt;
    let sourceReceipt;
    let blockedSourceState = '', lastSourceStatus = '';
    function reportSourceStatus(value) {
        if (disposed)
            return;
        const cleaned = sanitizeSourceStatus(value), key = JSON.stringify(cleaned);
        if (key !== lastSourceStatus) {
            lastSourceStatus = key;
            try {
                options.onSourceStatus?.(cleaned);
            }
            catch { } // Diagnostics cannot interrupt guarded execution.
        }
    }
    const sourceCapable = Boolean(options.captureSource && options.bindSource && options.confirmSource);
    const applications = options.apply ? createChartApplyController({ ...options, viewId, apply: options.apply,
        isActive: () => !disposed && options.isActive(), confirm: token => { if (!disposed)
            options.confirm?.(token); } }) : undefined;
    async function flush() {
        if (busy) {
            pending = true;
            return;
        }
        busy = true;
        try {
            do {
                pending = false;
                const active = !disposed && options.isActive();
                const state = disposed ? lastCaptured ?? { state: 'empty', candles: [], drawings: [] } : options.capture();
                lastCaptured = state;
                const serialized = JSON.stringify(state);
                const changed = serialized !== lastState;
                let feedback;
                if (!disposed && options.feedback) {
                    try {
                        feedback = options.feedback();
                    }
                    catch {
                        feedback = { report_status: 'invalid', items: [] };
                    }
                }
                const sourcePayload = !disposed && active && changed && sourceCapable && serialized !== blockedSourceState ? options.captureSource?.() : undefined;
                if (sourcePayload || sourceReceipt)
                    reportSourceStatus(sourceStatus('source_handoff_pending'));
                const response = await boundedPost({ conversation_id: options.conversationId, view_id: viewId, sequence: ++sequence, active,
                    captured_at_ms: Date.now(), application_protocol: applications ? 'guarded-view-v1' : undefined,
                    state: changed || lastActive === undefined || receipt || sourceReceipt ? state : null,
                    ...(sourceCapable ? { source_protocol: 'browser-source-v1' } : {}),
                    ...(sourcePayload ? { source_payload: sourcePayload } : {}), ...(sourceReceipt ? { source_receipt: sourceReceipt } : {}),
                    ...(feedback ? { drawing_feedback: feedback } : {}), ...(receipt ? { receipt } : {}) });
                lastState = serialized;
                lastActive = active;
                if (!disposed && options.onSourceStatus && JSON.stringify(options.capture()) !== serialized) {
                    reportSourceStatus(sourceStatus('source_handoff_pending'));
                    pending = true;
                }
                else
                    reportSourceStatus(response.source_status);
                if (receipt && response.receipt?.candidate_chart_session === receipt.candidate_chart_session
                    && response.receipt.lease_id === receipt.lease_id) {
                    applications?.confirm(response.receipt);
                    receipt = undefined;
                    lastState = ''; // Re-evaluate a deferred source handoff after a terminal application.
                }
                if (response.application) {
                    receipt = applications?.consume(response.application, response);
                    if (receipt)
                        pending = true;
                }
                if (sourceReceipt && response.source_receipt?.chart_session === sourceReceipt.chart_session
                    && ['confirmed', 'rejected'].includes(response.source_receipt.status)) {
                    if (!disposed)
                        options.confirmSource?.(sourceReceipt.chart_session, response.source_receipt.status === 'confirmed');
                    if (!disposed && response.source_receipt.status === 'rejected')
                        blockedSourceState = JSON.stringify(options.capture());
                    sourceReceipt = undefined;
                    lastState = '';
                    pending = true;
                }
                const offer = response.source_handoff;
                if (offer && sourceCapable && !sourceReceipt && !receipt && !disposed
                    && /^[A-Za-z0-9_-]{32}$/.test(offer.chart_session ?? '')) {
                    sourceReceipt = { chart_session: offer.chart_session, status: 'rejected' };
                    if (options.isActive() && offer.context_ref === response.context_ref && offer.expected_revision === response.revision
                        && offer.conversation_id === options.conversationId && offer.view_id === viewId
                        && Number.isSafeInteger(offer.expires_at_ms) && offer.expires_at_ms >= Date.now()
                        && observationKey(options.capture()) === observationKey(offer.base_state)) {
                        options.bindSource?.(offer.chart_session, offer.base_state.source_chart_session);
                        sourceReceipt.status = 'bound';
                    }
                    pending = true;
                }
            } while (pending);
        }
        catch {
            lastState = '';
            lastActive = undefined;
            reportSourceStatus(sourceStatus('context_transport_unavailable'));
        } // Heartbeat/receipt retry never queues a new drawing or refetches data.
        finally {
            busy = false;
            // A pending close must still run when the in-flight request failed.
            // With no newer notification, a failed close simply expires by TTL.
            if (pending) {
                pending = false;
                void flush();
            }
        }
    }
    function notify() {
        if (disposed || scheduled)
            return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; if (!disposed)
            void flush(); });
    }
    const heartbeat = setInterval(notify, 2000);
    const doc = typeof document === 'undefined' ? undefined : document;
    doc?.addEventListener('visibilitychange', notify);
    notify();
    return { notify, retrySource() {
            if (disposed)
                return;
            blockedSourceState = '';
            lastState = '';
            notify();
        }, dispose() {
            if (disposed)
                return;
            disposed = true;
            clearInterval(heartbeat);
            doc?.removeEventListener('visibilitychange', notify);
            for (const controller of inFlight)
                controller.abort();
            // A close queues behind the in-flight sample; sequence ordering prevents late revival.
            void flush();
        } };
}
