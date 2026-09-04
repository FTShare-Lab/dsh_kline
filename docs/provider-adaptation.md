# FTShare provider adaptation

## Scope

FTShare is an optional adapter. `analyze_kline_rows` is provider-neutral and must not call FTShare, configure credentials, or perform symbol lookup. Keep that path usable for broker feeds, backtests, crypto data, and custom labels.

A built-in free feed (`tools/free_sources.py`) is a separate fallback for the free/anonymous tier: it keeps **broad-market index data visible** (bottom market ticker, index daily candles, index comparison) when the current FTShare plan cannot serve it. It is deliberately limited to indices in a small explicit registry and never replaces FTShare as the promoted provider. Rows returned by the fallback are labeled `source=eastmoney_free` / `source=tencent_free` with a `source_url`, so the UI always shows where the data came from; nothing is ever presented as FTShare data. Individual stock minute/news depth remains an FTShare upsell, not a free feature.

## Contract source of truth

The official gateway documentation is the source of truth; the SDK is an implementation detail. The currently registered contracts are:

| Capability | Official documentation | Tier | Registered transports |
| --- | --- | --- | --- |
| Daily candles | [stock-candlesticks](https://market.ft.tech/gateway/doc/p/owq0364i) | Free | `http_get` → `sdk` |
| Historical minute candles | [stock-minutes](https://market.ft.tech/gateway/doc/p/z9lsvrvu) | Base | `http_get` → `sdk` |
| Index daily candles | [index-candlesticks](https://market.ft.tech/gateway/doc/p/gr2q0bjx) | Free | `sdk` |
| Index historical minute candles | [index-minutes](https://market.ft.tech/gateway/doc/p/ls85mq5n) | Base | `sdk` |

The pinned SDK is 1.0.3 and defaults to `https://market.ft.tech/gateway/`. The official [four-tier capability table](https://market.ft.tech/gateway/doc/p/pb8eizu3) is used for entitlement labels. Free endpoints are live-checked without paid credentials; paid endpoints are checked against official method names, paths, parameters, and symbol formats, but remain marked unverified until a permitted live request succeeds.

The registry in `tools/fetch.py` is intentionally small. Do not add a URL because an upstream response suggests it. Add a candidate only after checking its official documentation and testing its method, path, parameters, symbol format, authentication behavior, and response fields.

Each contract also carries `candidate_verification`. `true` means the candidate has passed a real request in the current verification cycle; `false` means it is documented but still requires a permitted live check. The status API exposes these flags so “registered” is not confused with “production-verified”.

A verification cycle ends when a release is published or the pinned SDK is upgraded. Re-run the upgrade checklist and refresh these flags in the same change; they are not permanent compatibility guarantees.

## Controlled fallback rules

- A successful transport is remembered in the current process and preferred on the next request.
- `401/403` is treated as authentication or plan state and does not switch transports.
- `429` retries the same transport with bounded backoff, then returns `rate_limited`; it does not multiply upstream traffic by switching methods.
- `404/405`, SDK method/signature mismatches, timeouts, and upstream `5xx` may advance to the next registered candidate.
- Every candidate attempt is bounded. No runtime code, URL, or contract is generated from remote data.
- Results and `data_source_status` expose the safe transport/contract status, never the API key.

## Broad-market index priority (official FTShare first)

A configured FTShare Key (any tier — index K-lines and global-index daily
K-lines are in the free tier per the official package table) keeps broad-market
data on the official feeds:

- A-share indices (`000001.XSHG`, `000300.XSHG`, `399001.XSHE`, …) use the
  registered `index_candlesticks` endpoint.
- Global indices (`100.HSI`, `100.NDX`, …) use the registered
  `global_index_daily_kline` endpoint; it returns daily bars only, and larger
  periods are aggregated locally.
- `fetch_market_ticker` and the bottom strip are official-first for all five
  listed indices and only downgrade to the built-in free quote feed when the
  official feeds return nothing (anonymous, no Key, or an upstream failure).

## Built-in free index fallback rules

`tools/free_sources.py` only runs after FTShare failed to return data for a **broad-market index** (its own registry: A-share/HK/US headline indices). Rules:

- FTShare is always tried first and its successful result is returned untouched.
- The fallback serves daily index K-lines from Eastmoney, then Tencent when Eastmoney is throttled or unreachable; both are public, key-less JSON feeds (no HTML scraping, no credentials).
- Responses are explicitly labeled (`eastmoney_free` / `tencent_free`) with a public `source_url`; the chart header and settings page render that source so users can tell free fallback from FTShare.
- Requests are bounded and cached in-process (short TTL); a free-source failure degrades silently back to the FTShare error — it must never break the primary chart.
- The bottom market ticker falls back to the Tencent quote feed only when FTShare returns no usable ticker items (official endpoints failed for most of the strip).
- Keep the registry small and explicit. Do not extend it to equities, minute bars, or unverified symbols: individual-stock depth is intentionally an FTShare capability.

## Upgrade checklist

1. Read the official package/tier page and each affected endpoint document.
2. Inspect the installed SDK signature and compare method names, required parameters, enums, symbol formats, and response fields with the registry.
3. Run redacted live checks for anonymous, free-tier, invalid-key, and permitted-capability cases when credentials are available.
4. Run `env PYTHONPATH=. pytest -q` and the provider smoke checks before changing the pinned SDK version or releasing.
5. Update `verified_sdk_version`, the registry documentation link, tests, README, and changelog together.

Never print or commit credentials. If the official contract changes in a way that is not covered by the registry, return a structured error and update the adapter manually.
