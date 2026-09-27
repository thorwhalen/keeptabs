"""Deciding whether an item belongs to a watch, and to which part of it.

A matcher is a function ``match(item, spec, *, mall) -> dict`` returning ``score``,
``subtopics``, ``entities`` and ``matched`` (the terms that hit). ``mall`` holds
the watch's stores, so a matcher can compare an item with what is already there
(near-duplicates, embeddings) or keep its own records. It may also return
``duplicate_of``, the id of a stored item that this one repeats, and entity ids
that the spec does not list yet: those are recorded as candidates.

:func:`keyword_matcher` is the default: whole-word, case-insensitive hits on
the spec's keywords and entity names, weighted by where they occur.
"""

import re
from functools import lru_cache

TITLE_WEIGHT = 2.0
BODY_WEIGHT = 1.0
PRIORITY_WEIGHT = {"high": 1.5, "medium": 1.0, "low": 0.5}


@lru_cache(maxsize=4096)
def _term_pattern(term: str):
    # \b fails next to non-word characters (as in "C++"), so look around for word chars
    return re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.IGNORECASE)


def _hits(term: str, title: str, body: str) -> float:
    pattern = _term_pattern(term)
    return TITLE_WEIGHT * bool(pattern.search(title)) + BODY_WEIGHT * bool(
        pattern.search(body)
    )


def keyword_matcher(item: dict, spec: dict, *, mall=None) -> dict:
    """Score an item against a spec's keywords, subtopics and entities.

    >>> spec = {'keywords': ['diffusion'], 'exclude_keywords': ['crypto'],
    ...     'subtopics': [{'id': 'video', 'priority': 'high', 'keywords': ['text-to-video']}],
    ...     'entities': [{'id': 'sora', 'name': 'Sora', 'aliases': []}]}
    >>> m = keyword_matcher({'title': 'Sora: a text-to-video diffusion model', 'summary': ''}, spec)
    >>> m['score'], m['subtopics'], m['entities']
    (7.0, ['video'], ['sora'])
    >>> keyword_matcher({'title': 'Diffusion of crypto', 'summary': ''}, spec)['score']
    0.0
    """
    title = item.get("title") or ""
    body = item.get("summary") or ""
    if any(_hits(term, title, body) for term in spec.get("exclude_keywords", [])):
        return {"score": 0.0, "subtopics": [], "entities": [], "matched": []}
    score, matched, subtopics, entities = 0.0, [], [], []
    for term in spec.get("keywords", []):
        hit = _hits(term, title, body)
        if hit:
            score += hit
            matched.append(term)
    for subtopic in spec.get("subtopics", []):
        weight = PRIORITY_WEIGHT.get(subtopic.get("priority", "medium"), 1.0)
        hits = [
            (term, _hits(term, title, body)) for term in subtopic.get("keywords", [])
        ]
        hits = [(term, hit) for term, hit in hits if hit]
        if hits:
            subtopics.append(subtopic["id"])
            score += weight * sum(hit for _, hit in hits)
            matched.extend(term for term, _ in hits)
    for entity in spec.get("entities", []):
        names = [entity["name"], *entity.get("aliases", [])]
        hit = max(_hits(name, title, body) for name in names)
        if hit:
            entities.append(entity["id"])
            score += hit
            matched.append(entity["name"])
    return {
        "score": round(score, 2),
        "subtopics": subtopics,
        "entities": entities,
        "matched": list(dict.fromkeys(matched)),
    }
