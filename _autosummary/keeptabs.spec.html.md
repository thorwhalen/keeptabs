# keeptabs.spec

The watch specification: what one tracked area is, and how it is watched.

A spec is a plain `dict` on disk (YAML) so an agent can read and write it without
this package. [`normalize_spec()`](#keeptabs.spec.normalize_spec) is the single place that fills defaults and
rejects what cannot work, so every other module may assume a complete spec.

### Functions

| [`as_bool`](#keeptabs.spec.as_bool)(value, \*, what)             | A yes or no, from a boolean or from the words for one.     |
|---------------------------------------------------------------------------------------|------------------------------------------------------------|
| [`blocked_source_ids`](#keeptabs.spec.blocked_source_ids)(spec)             | Sources that wait on a human action that is still open.    |
| [`normalize_source`](#keeptabs.spec.normalize_source)(source)             | One source with defaults filled in and its fields checked. |
| [`normalize_spec`](#keeptabs.spec.normalize_spec)(spec, \*[, watch_id]) | A complete, checked copy of a watch specification.         |
| [`str_list`](#keeptabs.spec.str_list)(value, \*[, what])          | A list of strings from what a hand-written spec may hold.  |
| [`target_field`](#keeptabs.spec.target_field)(kind)                   | The field of a source that says what to fetch.             |

### Exceptions

| [`SpecError`](#keeptabs.spec.SpecError)   | A watch specification that cannot be used, with the reason and the fix.   |
|--------------------------------------------------------------|---------------------------------------------------------------------------|

### *exception* keeptabs.spec.SpecError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A watch specification that cannot be used, with the reason and the fix.

### keeptabs.spec.as_bool(value, , what)

A yes or no, from a boolean or from the words for one.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> as_bool('false', what='enabled'), as_bool(True, what='enabled')
(False, True)
```

### keeptabs.spec.blocked_source_ids(spec)

Sources that wait on a human action that is still open.

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)

```pycon
>>> spec = normalize_spec({'id': 'w', 'sources': [{'kind': 'email', 'sender': 'a@b.c', 'id': 'nl'}],
...     'pending_actions': [{'action': 'Subscribe', 'blocks': ['nl']}]})
>>> blocked_source_ids(spec)
{'nl'}
```

### keeptabs.spec.normalize_source(source)

One source with defaults filled in and its fields checked.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> s = normalize_source({'kind': 'feed', 'url': 'https://example.com/feed.xml'})
>>> s['id'], s['cadence'], s['enabled'], s['keep_all']
('feed-https-example-com-feed-xml-7a775d', '1d', True, False)
```

A kind with no fetcher of its own is accepted, and says what to fetch in `target`:

```pycon
>>> normalize_source({'kind': 'my_api', 'target': 'robots', 'id': 'robots'})['id']
'robots'
```

### keeptabs.spec.normalize_spec(spec, , watch_id=None)

A complete, checked copy of a watch specification.

Only `id` (or `title`) is required: a spec starts as a vague idea.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> spec = normalize_spec({'title': 'Gen AI', 'keywords': ['diffusion'], 'entities': ['Sora']})
>>> spec['id'], spec['min_score'], spec['digest']['cadence'], spec['sources']
('gen-ai', 1.0, '1w', [])
>>> spec['entities']
[{'name': 'Sora', 'id': 'sora', 'kind': 'thing', 'aliases': []}]
```

### keeptabs.spec.str_list(value, , what='value')

A list of strings from what a hand-written spec may hold.

A bare string is one term, not a list of characters.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

```pycon
>>> str_list('diffusion'), str_list(['LLM', 2026]), str_list(None)
(['diffusion'], ['LLM', '2026'], [])
```

YAML reads an unquoted `NO` as false and `3.10` as 3.1. What was written
cannot be recovered, so such a term is refused, with the fix:

```pycon
>>> str_list(['LLM', False], what='keywords')
Traceback (most recent call last):
  ...
keeptabs.spec.SpecError: keywords holds False, which is not text. Put the term in quotes, as in "no" or "3.10".
```

### keeptabs.spec.target_field(kind)

The field of a source that says what to fetch.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> target_field('feed'), target_field('github_releases'), target_field('my_own_kind')
('url', 'repo', 'target')
```
