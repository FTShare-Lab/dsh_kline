# FTShare provider adaptation

## Scope

FTShare is an optional adapter. `analyze_kline_rows` is provider-neutral and must not call FTShare, configure credentials, or perform symbol lookup. Keep that path usable for broker feeds, backtests, crypto data, and custom labels.

## Contract source of truth

The official gateway documentation is the source of truth; the SDK is an implementation detail. The currently registered contracts are:

| Capability | Official documentation | Tier | Registered transports |
| --- | --- | --- | --- |
| Daily candles | [stock-candlesticks](https://market.ft.tech/gateway/doc/p/owq0364i) | Free | `http_get` → `sdk` |
| Historical minute candles | [stock-minutes](https://market.ft.tech/gateway/doc/p/z9lsvrvu) | Depends on plan | `http_get` → `sdk` |

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

## Upgrade checklist

1. Read the official package/tier page and each affected endpoint document.
2. Inspect the installed SDK signature and compare method names, required parameters, enums, symbol formats, and response fields with the registry.
3. Run redacted live checks for anonymous, free-tier, invalid-key, and permitted-capability cases when credentials are available.
4. Run `env PYTHONPATH=. pytest -q` and the provider smoke checks before changing the pinned SDK version or releasing.
5. Update `verified_sdk_version`, the registry documentation link, tests, README, and changelog together.

Never print or commit credentials. If the official contract changes in a way that is not covered by the registry, return a structured error and update the adapter manually.
