---
name: keeptabs-dev-architecture
description: The architecture of the keeptabs package, for the agent developing it - the five seams and their defaults, the module map, the one-command test, what is deliberately not built, and the research synthesis and prior art behind the design. Use before changing the shape of keeptabs, adding a module, adding a surface (MCP, HTTP), adding a dependency, or when asking "why is it built this way" or "what did the research recommend".
metadata:
  audience: developers
---

# keeptabs: architecture

## One-command test

```
keeptabs init-watch "Generative AI" --example gen-ai --watch-id gen-ai && keeptabs tick && keeptabs whats-new gen-ai --as-text
```

It must print a useful digest with every seam on its default. `tests/test_smoke.py` is the offline version and must pass after every change.

## Module map

| module | owns |
|---|---|
| `spec.py` | the spec schema: `normalize_spec` is the only place defaults and validation live |
| `stores.py` | where data lives: `spec_store`, `watch_mall` |
| `fetchers.py` | one function per source kind, all network access through `http_get` |
| `matching.py` | `keyword_matcher` |
| `engine.py` | `tick`: due-ness, fetch, dedupe, match, store, backoff |
| `digest.py` | `whats_new`, `render_markdown`, `deliver`, `make_digest` |
| `tools.py` | `TOOLS`: the single list every surface is built from |
| `__main__.py` | the CLI, one `cw.dispatch` over `TOOLS` |

## Seams (one keyword argument each)

| seam | argument | default | replacement that exists |
|---|---|---|---|
| where data lives | `rootdir=`, `specs=`, `malls=`, `lock=` | local YAML and JSON files through `dol`, a `filelock` lock | any `MutableMapping`, for example `s3dol` |
| how a source is fetched | `fetchers=`, `http_get=` | stdlib HTTP, `feedparser` | search APIs, a browser, `huggingface_hub` |
| relevance and matching | `matcher=`, called as `match(item, spec, *, mall)` | `keyword_matcher` | embeddings, model adjudication (see `keeptabs-dev-matching`) |
| digest writing | `summarizer=` | `render_markdown`, no model | a model that cites item ids only |
| delivery | `senders=` | `correspond` for email and GitHub, a webhook for Slack | `correspond`'s Slack channel when it exists |

Not seams, on purpose: scheduling (one idempotent `tick`, the platform's scheduler calls it), URL canonicalisation, the spec schema, CLI parsing.

## Surfaces

The CLI is built. MCP and HTTP are not: `tools.py` returns JSON-ready dicts and reads its stores, matcher and summarizer from `tools.components`, so `py2mcp.mk_mcp_from_refs(['keeptabs.tools:tick', ...])` needs no change to the core. Two skills ship to users in `keeptabs/data/skills/`.

## Rules that are easy to break

- **Nothing personal in the repository.** Real watch specs and acquired data live under the data directory. Tests use `tests/data/` fixtures with invented names on `example.org`.
- **Items before state.** `fetch_source` writes the item, then the cursor, so a crash repeats work and never loses it.
- **Nothing leaves the machine by default.** `deliver` is a dry run unless told otherwise, the scheduled digest sends only with `digest.auto_send`, and an imported spec cannot turn that on.
- **Fetched text is hostile.** Ids are checked before they become file names (`is_safe_id`: lowercase, at most 100 characters), and `escape_text` is applied to everything a digest prints. `tests/test_hardening.py` holds one test per finding of the two independent reviews.
- **Stores of your own come in a pair.** `tick(specs=..., malls=...)` takes no local lock and writes nothing locally.
- **A broken source never stops a tick.** Failures are recorded in state and reported in the digest.

## References

- `references/SUMMARY.md`: the research synthesis, with the recommended stack, what changed in 2025 and 2026, design risks and open questions.
- `references/prior-art.md`: existing tools and the methodology literature on technology watch.
