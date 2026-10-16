/** Merge a drawing-only result into its owning view, preserving candles and toggles. */
const AI_DRAWING_COMMANDS = new Set(['DRAW_HORIZONTAL_LINE', 'DRAW_AGENT_TREND_LINE', 'DRAW_AGENT_CHANNEL', 'DRAW_AGENT_RECTANGLE'])

export function mergeHorizontalLineSnapshot(payload: any, saved: any): any {
  if (payload?.drawing_guard || payload?.view_source_guard || !payload?.drawing_only || saved?.session !== payload.drawing_parent_session
    || saved?.payload?.symbol !== payload.symbol || saved?.payload?.interval !== payload.interval
    || !Array.isArray(saved?.payload?.chartCommands)) return undefined
  const { _live_chart_session, _live_application_pending, ...savedPayload } = saved.payload
  return {
    ...savedPayload,
    drawing_only: true,
    drawing_parent_session: payload.drawing_parent_session,
    indicators_explicit: false,
    chartCommands: [
      ...saved.payload.chartCommands.filter((command: any) => !AI_DRAWING_COMMANDS.has(command.type)),
      ...payload.chartCommands.filter((command: any) => AI_DRAWING_COMMANDS.has(command.type)),
    ],
  }
}
