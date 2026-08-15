# Architecture

`dsh_kline` is an integration layer between DeepSeek Harness and the existing
`ft-kline-view` MCP server. It does not copy or fork the chart, indicator, or
watchlist implementation.

## Data flow

```text
DeepSeek model
  -> DeepSeek Harness agent loop
  -> @deepseek-ai/dsh-mcp-client
  -> ft-kline-view over stdio MCP
  -> FTShare Python SDK inside ft-kline-view (fetch_candles)
  -> calc_metrics / draw_kline
```

The MCP bridge exposes tools under names such as:

```text
mcp__ft-kline-view__calc_metrics
mcp__ft-kline-view__draw_kline
mcp__ft-kline-view__doctor_view
```

The opt-in `ft-kline-view-with-ftshare.patch.yml` profile additionally mounts
the public FTShare-MCP Streamable HTTP server for finance-data workflows that
are outside the chart server's built-in provider.

The default chart path keeps the data-provider decision inside
`ft-kline-view`: its `fetch_candles` tool calls the FTShare Python SDK and
returns canonical rows. This keeps dsh's tool surface small and avoids making
the model orchestrate a data call followed by a chart call.

## Current boundary

The first integration milestone bridges MCP tools only. DeepSeek Harness
`0.1.0-rc.6` does not consume MCP resources or prompts through its MCP client.
Consequently, tool discovery and structured results can be verified now, but
the existing MCP App resource returned by `draw_kline` is not expected to render
inside the dsh Web UI.

Chart presentation will be handled as a separate milestone after the tool-call
path is stable. Candidate approaches are:

1. add a native dsh client plugin that renders the existing chart commands;
2. publish a standalone chart URL/artifact from `ft-kline-view`;
3. extend the dsh MCP bridge if upstream adds MCP resource support.

## Version policy

DeepSeek Harness is pinned exactly because it is in developer preview and may
introduce breaking changes. Upgrades require:

1. lockfile update;
2. profile dump comparison;
3. MCP discovery smoke test;
4. keyless tool-call contract tests;
5. one real-API end-to-end task when a development API key is available.
