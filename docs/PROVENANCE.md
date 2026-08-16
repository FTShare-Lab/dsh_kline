# Provenance

The standalone MCP server includes adapted OHLCV normalization, FTShare provider,
and deterministic indicator code originally developed in the MIT-licensed
`ft-kline-view` project. The code is maintained in this repository so users do
not need another MCP server or checkout at runtime.

The copied modules were imported from the local `ft-kline-view` release line at
version `0.1.55` and then adapted for the smaller dsh-specific tool surface.
Future changes should be ported deliberately with regression tests rather than
by adding a runtime dependency on that repository.
