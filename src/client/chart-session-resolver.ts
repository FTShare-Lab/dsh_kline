import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { chartStorageKey, latestChart, latestChartFromEvents, type ChartReference, type Sessions } from './conversation'
const EMPTY_CONVERSATION = { nodes: [] }
const EMPTY_EVENTS = { entries: [] }
export function useChartReference(sessions: Sessions, conversationId?: string, onNewChart?: (reference: ChartReference) => void) {
  const mountedAt = useRef(Date.now())
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
  const [reference, setReference] = useState<ChartReference | undefined>(() => {
    if (!conversationId) return undefined
    try {
      const value = JSON.parse(localStorage.getItem(chartStorageKey(conversationId)) ?? 'null')
      return /^[A-Za-z0-9_-]{32}$/.test(value?.session) ? value : undefined
    } catch { return undefined }
  })
  useEffect(() => {
    if (!conversationId || !discovered || (reference && reference.order >= discovered.order)) return
    setReference(discovered)
    // Reveal results produced while this conversation is on screen. Merely
    // reopening historical messages must not override the user's closed panel.
    if (discovered.order >= mountedAt.current) onNewChart?.(discovered)
    try { localStorage.setItem(chartStorageKey(conversationId), JSON.stringify(discovered)) } catch {}
  }, [conversationId, discovered?.session, discovered?.order, reference, onNewChart])
  return reference
}
