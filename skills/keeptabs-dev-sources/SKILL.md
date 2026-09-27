---
name: keeptabs-dev-sources
description: How to add or change a source kind in the keeptabs package - the fetcher contract, conditional requests, cursors, the offline test fixture, and the researched options for feeds, full-text extraction, newsletters by email, research and code APIs, and web search. Use when adding a fetcher (Hugging Face, Reddit, OpenAlex, a search API, a browser), changing how newsletters are read, debugging a source that fails or returns nothing, or choosing a library for ingestion.
metadata:
  audience: developers
---

# keeptabs: sources and fetchers

## The contract

```python
def fetch_<kind>(source, *, state, http_get=http_get) -> tuple[list[dict], dict]:
```

- `source` is a normalized source record. Its target field is named in `SOURCE_TARGET_FIELD` in `keeptabs/spec.py`, and is `target` for a kind that is not listed there.
- `state` is the cursor this fetcher returned last time. Return the new one.
- Every request goes through `http_get`. A fetcher that opens its own connection cannot be tested offline.
- Each raw item has `url` and `title`, and when known `summary`, `published` (ISO 8601), `author`, `guid`.
- Raise on failure. The engine records the error, backs off, and carries on with the other sources.

## Adding a kind

1. Write `fetch_<kind>` in `keeptabs/fetchers.py` and add it to `DEFAULT_FETCHERS`.
2. Add the kind to `SOURCE_KINDS` in `keeptabs/spec.py`, and to `SOURCE_TARGET_FIELD` if its target deserves a better name than `target`.
3. Add a fixture under `tests/data/` with invented content, a route in `tests/conftest.py`, and a source in the test spec.
4. Add the row to the table in `keeptabs/data/skills/keeptabs-spec/SKILL.md`.
5. A kind that needs a key or a heavy library goes behind an optional extra, imported inside the function.

## Newsletters

Mail is read through `correspond`, never directly. Two gaps are filed there: the HTML part and the list headers (issue 38), and a folder or label per call (issue 39). Until they land, `fetch_email` works from the single body `correspond` returns and filters by sender.

## References

- `references/ingestion-feeds.md`: feed parsing, discovery, conditional requests, full-text extraction, and the APIs of arXiv, GitHub, Hugging Face, Hacker News and others.
- `references/ingestion-newsletters.md`: reading a mailbox, routing per topic, parsing newsletter HTML, tracking redirects, terms of service.
- `references/search.md`: web search options, their costs and limits, and generating queries from a spec.
