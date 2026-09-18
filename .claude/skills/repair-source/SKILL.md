---
name: repair-source
description: Diagnose one failing apartment source adapter with a small fixture and test.
---

Read the affected source status and docs/COLLECTION.md. Reproduce with a minimal sanitized offline fixture. Distinguish changed selectors, explicit empty inventory, blocked access and network errors. Fix the shared adapter, run focused tests, and perform at most one permitted bounded probe. Do not use a browser to evade a provider restriction. Avoid loading full archives or private configuration into prompts. Report parser correctness separately from live access.

Use `--workspace PATH` before the subcommand when needed. Run commands through `uv run` in a checkout.
