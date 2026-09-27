# keeptabs

Seams (one keyword argument each): storage `rootdir=`/`specs=` (local files), fetching `fetchers=`/`http_get=` (stdlib + feedparser), matching `matcher=` (keywords), digest writing `summarizer=` (Markdown, no model), delivery `senders=` (correspond, Slack webhook).
Surfaces built: CLI (`cw` over `keeptabs/tools.py:TOOLS`) and two shipped skills. MCP and HTTP are not built and need no core change.
One-command test: `keeptabs init-watch "Generative AI" --example gen-ai --watch-id gen-ai && keeptabs tick && keeptabs whats-new gen-ai --as-text`.

## Rules

- This repository is public. Real watch specifications and acquired data never enter it: they live under the data directory. Tests use invented content on `example.org`.
- All network access goes through `http_get`, so every test runs offline.
- Mail and messaging go through `correspond`. Needs there are filed as issues on that repository, not worked around here.

## Dev skills (in `skills/`, linked from `.claude/skills/`)

| Skill | Use it when |
|---|---|
| `keeptabs-dev-architecture` | changing the shape, adding a surface or a dependency; holds the research synthesis and prior art |
| `keeptabs-dev-sources` | adding or fixing a source kind; holds the ingestion, newsletter and search research |
| `keeptabs-dev-matching` | changing relevance, deduplication or entity matching; holds that research |
| `keeptabs-dev-scheduling-digests` | changing `tick`, digests or delivery; holds that research |

Skills shipped to users are in `keeptabs/data/skills/`: `keeptabs-spec`, `keeptabs-ask`.
