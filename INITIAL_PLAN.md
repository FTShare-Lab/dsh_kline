# dsh_kline Local Release Plan

Status date: 2026-08-17

This file is intentionally ignored by Git.

## Goal

Publish `FTShare-Lab/dsh_kline` as one self-contained DeepSeek Harness K-line
MCP repository. Users must not clone, configure, or start another MCP project.

```text
dsh -> bundled dsh_kline MCP -> installed FTShare SDK
```

## Release Claim

The repository provides a small dsh-specific tool surface for FTShare-backed
K-line retrieval and deterministic indicators. `analyze_kline` performs fetch,
calculation, and chart-spec generation against one canonical row set.

The release exposes the interactive chart inside a native DeepSeek Harness
right sidebar. The MCP-owned loopback URL remains the chart transport and a
host-independent fallback, but users do not need to open a separate tab.

## Completed

- [x] Pin DeepSeek Harness `0.1.0-rc.6`.
- [x] Add the standalone Python MCP server to this repository.
- [x] Copy and adapt the proven FTShare provider, OHLCV normalization, and
      deterministic indicator implementation under the MIT license.
- [x] Remove external K-line MCP and FTShare-MCP profiles.
- [x] Remove sibling-repository discovery from runtime code.
- [x] Expose only `health`, `fetch_candles`, `calc_metrics`, and
      `analyze_kline`.
- [x] Verify stdio discovery of all four tools.
- [x] Copy the verified interactive frontend and vendored chart bundle into
      `view/` without modifying or depending on `ft-kline-view` at runtime.
- [x] Remove MCP Apps postMessage, window.openai, and ui/initialize host
      handshake code from the dsh chart page.
- [x] Add loopback-only chart sessions with expiring in-memory payloads and a
      `chart_url` returned by `analyze_kline`.
- [x] Route chart search, range, comparison, and security-workspace requests
      through same-origin `/api/tools/*` endpoints.
- [x] Preserve `chart.rows` and the four-tool MCP surface for Harness callers.
- [x] Pass 68 local unit, chart payload, session, frontend-contract, and MCP
      regression tests.
- [x] Pass frontend JavaScript syntax and whitespace checks.
- [x] Inspect a real FTShare chart at desktop and mobile breakpoints, including
      indicators, crosshair, zoom, drag, theme, language, and local expand.
- [x] Fix mobile quote wrapping and make the indicator toolbar independently
      horizontally scrollable.
- [x] Page generic daily-or-larger FTShare history inside its 12-month request
      limit; retain larger 1Y/5Y chart ranges.
- [x] Fetch additional source rows when a range switch exceeds the initial
      chart session; verify the real A-share 5Y chart reaches August 2021.
- [x] Run a black-box dsh Web session as an ordinary user and verify the
      single-call analysis path, chart URL, market search, invalid-symbol
      handling, time ranges, indicators, zoom, drag, crosshair, and reset.
- [x] Verify the real chart at 1280x720 and 390x844 without page overflow;
      add those desktop and mobile screenshots to the Chinese README.
- [x] Remove the duplicate custom MA value legend and use KLineCharts' native
      MA indicator for both lines and values.
- [x] Make the initial persisted range fetch enough rows before first render,
      and localize remaining chart accessibility labels.
- [x] Tighten MCP instructions so ordinary requests call `analyze_kline`
      exactly once and stop cleanly on provider errors.
- [x] Connect the existing support/resistance metric to `analyze_kline` chart
      annotations and preserve those labels across local range redraws and
      same-symbol refreshes.
- [x] Rework the Chinese README around one primary FTShare chart screenshot,
      feature-specific annotation/mobile screenshots, and a verified Harness
      single-call screenshot without credentials.
- [x] Document FTShare SDK as the recommended, default-installed optional data
      source while keeping the provider-neutral OHLCV calculation contract.
- [x] Add a DSH dual-half bundle that mounts the existing interactive chart in
      a native collapsible and resizable right sidebar.
- [x] Make `pnpm dsh:web` build and register the local bundle automatically;
      users do not start a separate MCP or chart service.
- [x] Publish the latest live chart session through a same-origin DSH endpoint,
      reject stale process manifests, and retain `chart_url` compatibility.
- [x] Verify the bundle in an isolated DSH profile: boot manifest, served client
      bundle, desktop 1280x720 layout, mobile 390x844 overlay, collapse, resize,
      MA toggle, and zero page-width overflow.
- [x] Add a credential-free Harness sidebar screenshot to the Chinese README.

## Remaining Release Gates

- [x] Pass all copied provider/indicator tests and standalone server tests.
- [x] Build `.venv` using only this repository's `requirements.txt`.
- [x] Run a real FTShare `00700.HK` analysis from the standalone server.
- [x] Run one real DeepSeek Web task that calls only
      `mcp__dsh-kline__analyze_kline`.
- [x] Clone into a clean directory with no `ft-kline-view` sibling and repeat
      install, tests, discovery, and live analysis.
- [x] Scan tracked files for secrets, machine paths, and old external MCP refs.
- [x] Run the real HK, US, and A-share regression through dsh Web, including
      malformed-symbol and unsupported-interval failures.
- [x] Pass unrestricted local `pnpm smoke:live` and `pnpm smoke:markets` runs
      against FTShare for HK, US, and A-share data.
- [x] Inspect a returned real FTShare chart URL in desktop and mobile browser
      viewports.
- [x] Start dsh Web, call `analyze_kline` once, and inspect the returned real
      FTShare chart URL.
- [x] Commit the standalone release as `9053a65`.
- [x] Push `9053a65` to `origin/main`; verify `main...origin/main` is aligned.
- [x] Confirm the pinned FTShare Python SDK tarball installs without Git credentials.
- [ ] Rotate the DeepSeek API key previously pasted in chat; never record the
      replacement in this repository or release artifacts.
- [ ] Ask the administrator to change `FTShare-Lab/dsh_kline` to public only
      after every previous gate passes.
- [ ] Decide whether to create tag `v0.1.0` after external review.

## Risks

| Risk | Treatment |
| --- | --- |
| dsh developer-preview changes | Pin the exact version and regression test upgrades. |
| MCP Apps rendering differs by host | Use DSH's native client bundle for the sidebar and retain `chart_url` fallback. |
| Model reconstructs market rows | Make `analyze_kline` the primary single-call path. |
| FTShare SDK cannot be installed anonymously | Do not publish until its Git dependency is public and reproducible. |
| Copied implementation drifts | Keep provenance and focused provider/indicator regression tests. |
| API key exposure | Keep credentials outside Git and rotate pasted keys. |
## 2026-08-20 UI layout update

- Moved workspace tabs out of the brand/search/action row into a dedicated row between workspace controls and the security header.
- Tabs now appear only when two or more symbols are open; they remain single-line and horizontally scrollable.
- Kept the existing chart metadata separation and inset percent-axis labels so the top and bottom change markers do not overlap chart content.
