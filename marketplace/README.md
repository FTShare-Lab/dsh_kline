# FTShare GitHub plugin source

`ft-kline/` is the complete, installable Codex plugin snapshot. It is generated
from the same allowlist and files as the Codex ZIP, with no source build required
on the user's machine. The root `.agents/plugins/marketplace.json` exposes it as
`ft-kline@ftshare`.

Edit canonical runtime files at the repository root and plugin manifests under
`plugins/ft-kline/`, then run:

```bash
pnpm sync:codex-marketplace
pnpm verify:codex-marketplace
```

Commit the generated snapshot together with the source changes. CI checks every
file against the package sources and runs the copied snapshot independently in
both Desktop and CLI modes. Do not edit generated files directly. Changes to
runtime behavior must also follow the normal plugin version/release process.

The public source follows `main`; install candidates with `--ref test` only for
acceptance testing. User installation and update instructions are in the root
[README](../README.en.md#use-with-codex).
