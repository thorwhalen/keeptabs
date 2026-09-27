# keeptabs.matching

Deciding whether an item belongs to a watch, and to which part of it.

A matcher is a function `match(item, spec, *, mall) -> dict` returning `score`,
`subtopics`, `entities` and `matched` (the terms that hit). `mall` holds
the watch’s stores, so a matcher can compare an item with what is already there
(near-duplicates, embeddings) or keep its own records. It may also return
`duplicate_of`, the id of a stored item that this one repeats, and entity ids
that the spec does not list yet: those are recorded as candidates.

[`keyword_matcher()`](#keeptabs.matching.keyword_matcher) is the default: whole-word, case-insensitive hits on
the spec’s keywords and entity names, weighted by where they occur.

### Functions

| [`keyword_matcher`](#keeptabs.matching.keyword_matcher)(item, spec, \*[, mall])   | Score an item against a spec's keywords, subtopics and entities.   |
|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------|

### keeptabs.matching.keyword_matcher(item, spec, , mall=None)

Score an item against a spec’s keywords, subtopics and entities.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> spec = {'keywords': ['diffusion'], 'exclude_keywords': ['crypto'],
...     'subtopics': [{'id': 'video', 'priority': 'high', 'keywords': ['text-to-video']}],
...     'entities': [{'id': 'sora', 'name': 'Sora', 'aliases': []}]}
>>> m = keyword_matcher({'title': 'Sora: a text-to-video diffusion model', 'summary': ''}, spec)
>>> m['score'], m['subtopics'], m['entities']
(7.0, ['video'], ['sora'])
>>> keyword_matcher({'title': 'Diffusion of crypto', 'summary': ''}, spec)['score']
0.0
```
