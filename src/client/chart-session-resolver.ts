import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { latestChart, latestChartFromEvents, type ChartReference, type Sessions } from './conversation'
const EMPTY_CONVERSATION = { nodes: [] }
const EMPTY_EVENTS = { entries: [] }
export function useChartReference(sessions: Sessions, conversationId?: string, onNewChart?: (reference: ChartReference) => void) {
  const readyForNewCharts = useRef(false)
  const binding = conversationId ? sessions.binding(conversationId) : undefined
  const face = binding?.eventSource ? undefined : binding?.session
  const conversation = useSyncExternalStore(
    listener => face?.subscribe(listener) ?? (() => {}),
    () => face?.getSnapshot() ?? EMPTY_CONVERSATION,
  )
  const eventSource = binding?.eventSource
  const events = useSyncExternalStore(
    listener => eventSource?.subscribe(listener) ?? (() => {}),
    () => eventSource?.getSnapshot() ?? EMPTY_EVENTS,
  )
  const discovered = useMemo(() => eventSource
    ? latestChartFromEvents(events.entries)
    : latestChart(conversation.nodes ?? []), [eventSource, events.entries, conversation.nodes])
  // Event timestamps are host-specific and are not guaranteed to use the
  // browser's millisecond clock.  Capture the chart already present at mount
  // instead of comparing incompatible timestamps.
  const initialChartSession = useRef(discovered?.session)
  // A chart is authoritative only when it is present in this conversation's
  // live session history.  Restoring a browser cache here can make a fresh
  // DSH conversation inherit an old chart, bypassing the Market launcher.
  const [reference, setReference] = useState<ChartReference | undefined>()
  useEffect(() => {
    // DSH's event window can arrive one subscription tick after this hook
    // mounts. Treat that short hydration window as historical state, not as a
    // new analysis that should replace the Market launcher.
    const timer = window.setTimeout(() => { readyForNewCharts.current = true }, 350)
    return () => { window.clearTimeout(timer) }
  }, [conversationId])
  useEffect(() => {
    if (!conversationId || !discovered || (reference && reference.order >= discovered.order)) return
    setReference(discovered)
    // Reveal only a result that appeared after this hook mounted. Merely
    // reopening historical messages must not override the Market launcher.
    if (readyForNewCharts.current && discovered.session !== initialChartSession.current) onNewChart?.(discovered)
  }, [conversationId, discovered?.session, discovered?.order, reference, onNewChart])
  return reference
}
