---
name: refresh-search
description: Refresh configured apartment sources with bounded requests and compact summaries.
---

Run `housing status --json` and `housing sources check`, then `housing refresh`. Inspect each source status and review count. Do not treat missing records after a failed or partial run as off-market. Do not expand the source set without a concrete need. Rerun routes only when relevant geometry, scenario or network inputs changed. Report useful changes and unresolved coverage; never claim complete city inventory.

Use `--workspace PATH` before the subcommand when needed. Run commands through `uv run` in a checkout.
