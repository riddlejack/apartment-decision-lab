---
name: setup-search
description: Set up a private apartment search using the installed housing CLI.
---

Run `housing doctor`. Use `housing init` for real data or a separate `housing demo` workspace. Import user-provided CSV/JSON and inspect `housing status --json`. Open `housing review` to configure people and destinations. For collection read docs/COLLECTION.md; for routes read docs/ROUTING.md. Confirm actual available capabilities, never assume browser or routing tools exist. Keep household coordinates out of Git. Report what works and what requires source/feed setup.

Use `--workspace PATH` before the subcommand when needed. Run commands through `uv run` in a checkout.
