---
name: keeptabs-dev-matching
description: How relevance scoring, deduplication and entity matching work in the keeptabs package, and the researched ways to strengthen them - URL canonicalisation, near-duplicate detection, embeddings, entity resolution, novelty scoring, story clustering. Use when a watch is too noisy or misses items, when the same story is stored twice, when changing keyword_matcher or canonical_url, or when adding an embedding or model-based matcher.
metadata:
  audience: developers
---

# keeptabs: matching and deduplication

## What v1 does

- **Identity.** An item's id is a hash of its canonical URL (`keeptabs/util.py`, `canonical_url`). The tracking parameters to drop are data, in `TRACKING_PARAMS` and `TRACKING_PARAM_PREFIXES`.
- **Relevance.** `keyword_matcher` in `keeptabs/matching.py` counts whole-word, case-insensitive hits, weighting the title over the body and a subtopic by its priority. An item is kept when its score reaches the spec's `min_score`, or when its source has `keep_all`.
- **Entities.** A hit on an entity's name or alias links the item to it. The engine updates the entity's record with the time and the item id.

## What v1 does not do

Near-duplicate detection across different URLs, discovery of new entities, and story clustering. The references say how; each enters through the `matcher=` argument of `tick` or as a step after it, not as a change to callers.

## Replacing the matcher

A matcher is `match(item, spec, *, mall) -> {"score", "subtopics", "entities", "matched"}`. Keep the keys: the digest and the `items` tool read them. It may add `duplicate_of` (the id of the stored item this one repeats, which sends it to the `dropped` store) and may name entity ids the spec does not list, which are stored with the kind `candidate`. Each item is judged once: kept or dropped, it is not passed to the matcher again. Test a new matcher against `tests/data/feed.xml`, which holds two relevant entries and one irrelevant one.

## References

- `references/dedup-matching.md`: canonicalisation, SimHash and MinHash, embeddings, record linkage, novelty and relevance scoring, clustering.
