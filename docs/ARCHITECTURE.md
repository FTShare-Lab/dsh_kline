# Architecture

`dsh_kline` is a standalone MCP server and DeepSeek Harness profile. The
repository owns its complete runtime tool path.

## Runtime

```text
dsh agent loop
  -> dsh MCP client
  -> local stdio server (`server.py`)
       -> installed FTShare Python SDK
       -> `tools.fetch.fetch_candles`
       -> `core.rows` normalization
       -> `core.calc` deterministic calculations
       -> compact text result and structured chart data
       -> `chart_service` session store and loopback chart URL

The chart URL serves the vendored `view/kline.html` and `view/vendor/klinecharts.min.js`
from the same process. The page calls same-origin `/api/tools/*` routes for
range changes, symbol search, comparisons, and optional security workspace data.
It does not use MCP Apps `postMessage`, `window.openai`, or a resource handshake.
```

The process does not connect to FTShare-MCP, spawn another MCP process, import
another repository, or discover sibling project directories. `FTSHARE_SDK_SRC`
is an optional library-development override; normal installations use the SDK
installed in `.venv`.

Generic daily-or-larger FTShare history is paged backwards in windows of at
most 360 days. This respects the provider's 12-natural-month request limit and
lets 1Y/5Y frontend requests collect enough rows without changing the MCP tool
contract.

## Tool Design

`analyze_kline` is the model-facing product path. It overfetches a calendar
window, keeps the requested latest bars, computes all requested values against
that exact row set, and returns:

- compact JSON in the MCP text block for the model;
- canonical rows and a provider-neutral chart specification in
  `structuredContent`;
- `chart_url` and `chart_session` for the standalone browser view.

`fetch_candles` and `calc_metrics` remain available for debugging and capable
MCP hosts, but current dsh prompts should not chain them because dsh does not
retain structured results for model composition.

## Version Policy

DeepSeek Harness is pinned while it remains in developer preview. Upgrades
require a lockfile update, profile-dump comparison, unit tests, stdio discovery,
one live FTShare call, and one real dsh Web task.
