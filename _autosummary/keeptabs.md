# keeptabs

Keep tabs on the subjects you care about (technology watch; in French, “veille”).

Describe what to follow as watch specifications, let a scheduled `tick` acquire
and match what is new, and ask “what’s new” whenever you like.

By watch id, with everything on its default (this is what the command line runs):

```pycon
>>> from keeptabs import tools
>>> tools.tick()
>>> tools.whats_new('gen-ai', since='3d')
```

With parts of your own (stores, fetchers, a matcher, a summarizer, senders):

```pycon
>>> from keeptabs import tick, whats_new, make_digest
```

### Functions

| [`deliver`](#keeptabs.deliver)(text, channels, \*, title[, dry_run, ...])   | Send a digest to each channel reference, such as `email:me@example.org`, `github:owner/repo#12` (a discussion) or `slack:`.    |
|-------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`escape_text`](#keeptabs.escape_text)(text)                                    | Text that renders as itself, on one line, in Markdown and in HTML: no link, tag, mention, heading or emphasis of its own.      |
| [`http_get`](#keeptabs.http_get)(url, \*[, etag, last_modified, timeout])    | GET a URL politely: identified, and conditional when validators are known.                                                     |
| [`keyword_matcher`](#keeptabs.keyword_matcher)(item, spec, \*[, mall])              | Score an item against a spec's keywords, subtopics and entities.                                                               |
| [`make_digest`](#keeptabs.make_digest)(spec, mall, \*[, since, now, ...])       | Build a digest, store it, and deliver it (for real only when `send`).                                                          |
| [`memory_mall`](#keeptabs.memory_mall)()                                        | The stores of one watch, in memory: for tests and throwaway runs.                                                              |
| [`normalize_spec`](#keeptabs.normalize_spec)(spec, \*[, watch_id])                 | A complete, checked copy of a watch specification.                                                                             |
| [`render_markdown`](#keeptabs.render_markdown)(digest)                              | A digest as Markdown, with no model involved.                                                                                  |
| [`scheduled_digest`](#keeptabs.scheduled_digest)(\*[, summarizer, senders])          | The `on_digest_due` callback for [`keeptabs.engine.tick()`](keeptabs.engine.md#keeptabs.engine.tick). |
| [`spec_store`](#keeptabs.spec_store)([rootdir])                                | Watch specifications, keyed by watch id, stored as YAML files.                                                                 |
| [`tick`](#keeptabs.tick)([watch_ids, rootdir, specs, malls, ...])        | Run everything that is due, once, and say what happened.                                                                       |
| [`watch_mall`](#keeptabs.watch_mall)(watch_id, \*[, rootdir])                  | The stores of one watch.                                                                                                       |
| [`whats_new`](#keeptabs.whats_new)(spec, mall, \*[, since, max_items, now])   | The items acquired since `since`, grouped by subtopic, best first.                                                             |

### Classes

| [`Response`](#keeptabs.Response)(status[, body, headers])   | What a fetcher needs from an HTTP exchange.   |
|--------------------------------------------------------------------------------------|-----------------------------------------------|

### Exceptions

| [`AlreadyRunning`](#keeptabs.AlreadyRunning)   | Another tick holds the lock.                                            |
|-------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`SpecError`](#keeptabs.SpecError)        | A watch specification that cannot be used, with the reason and the fix. |

### *exception* keeptabs.AlreadyRunning

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Another tick holds the lock.

### *class* keeptabs.Response(status, body=b'', headers=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a fetcher needs from an HTTP exchange.

### *exception* keeptabs.SpecError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A watch specification that cannot be used, with the reason and the fix.

### keeptabs.deliver(text, channels, , title, dry_run=True, senders=None)

Send a digest to each channel reference, such as `email:me@example.org`,
`github:owner/repo#12` (a discussion) or `slack:`.

Dry-run by default: a real send reaches people and cannot be unsent. One
failing channel does not stop the others.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### keeptabs.escape_text(text)

Text that renders as itself, on one line, in Markdown and in HTML: no link,
tag, mention, heading or emphasis of its own.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> print(escape_text('Sprout <!channel> [click](https://evil.example) & co'))
Sprout &lt;!channel&gt; \[click\](https://evil.example) &amp; co
>>> print(escape_text('ping @someone about #12\n# A heading'))
ping &#64;someone about &#35;12 &#35; A heading
```

### keeptabs.http_get(url, , etag=None, last_modified=None, timeout=30)

GET a URL politely: identified, and conditional when validators are known.

* **Return type:**
  [`Response`](keeptabs.fetchers.md#keeptabs.fetchers.Response)

### keeptabs.keyword_matcher(item, spec, , mall=None)

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

### keeptabs.make_digest(spec, mall, , since=None, now=None, summarizer=None, send=False, senders=None, mark_reported=None)

Build a digest, store it, and deliver it (for real only when `send`).

`mark_reported` says whether the items count as reported from now on, so the
next digest leaves them out. It defaults to `send`: a dry run changes nothing,
and can be followed by the real send of the same digest. Items are never marked
when a delivery failed, so a digest that did not arrive is sent again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.memory_mall()

The stores of one watch, in memory: for tests and throwaway runs.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> sorted(memory_mall()) == sorted(STORE_KINDS)
True
```

### keeptabs.normalize_spec(spec, , watch_id=None)

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

### keeptabs.render_markdown(digest)

A digest as Markdown, with no model involved.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> print(render_markdown({'title': 'Gen AI', 'since': '2026-01-01T00:00:00+00:00',
...     'until': '2026-01-08T00:00:00+00:00', 'total_new': 1, 'shown': 1, 'sections': [
...     {'id': 'video', 'title': 'Video', 'items': [{'title': 'A model', 'url': 'https://example.com/a',
...     'summary': 'It generates.', 'published': '2026-01-05T00:00:00+00:00', 'source': 'blog'}]}],
...     'new_entities': [], 'active_entities': [], 'failing_sources': []}))
# What's new: Gen AI

2026-01-01 to 2026-01-08. 1 new item.

## Video

- [A model](https://example.com/a) (blog, 2026-01-05). It generates.
```

### keeptabs.scheduled_digest(, summarizer=None, senders=None)

The `on_digest_due` callback for [`keeptabs.engine.tick()`](keeptabs.engine.md#keeptabs.engine.tick).

A period with nothing new is skipped. Otherwise the digest is written to the
`digests` store, and:

- with `digest.auto_send: true`, it is sent, and its items count as reported
  once every channel took it;
- with channels but no `auto_send`, nothing is sent and nothing is marked:
  the items wait for the owner’s `digest --send`;
- with no channel at all, the stored digest is the report.

### keeptabs.spec_store(rootdir=None)

Watch specifications, keyed by watch id, stored as YAML files.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

### keeptabs.tick(watch_ids=None, , rootdir=None, specs=None, malls=None, fetchers=None, http_get=None, matcher=None, on_digest_due=None, lock=None, now=None, force=False)

Run everything that is due, once, and say what happened.

- `specs`: the store of watch specifications (default: local files under `rootdir`).
- `malls`: a function from a watch id to that watch’s stores (default: local files).
  Stores of your own come in a pair: give both `specs` and `malls`.
- `fetchers`: source kind to fetcher, added to the defaults.
- `http_get`: the one door to the network.
- `matcher`: `match(item, spec, *, mall)`, scoring an item against a spec.
- `on_digest_due`: called with `(spec, mall, now)` for each watch whose digest is
  due (default: [`keeptabs.digest.scheduled_digest()`](keeptabs.digest.md#keeptabs.digest.scheduled_digest)); `False` for no digest.
- `lock`: a context manager held for the run, or `False` for none. The default
  is a local file lock, and none when the stores are your own.
- `force`: run every enabled, unblocked source whatever its schedule.

A watch or a source that fails is reported in `failures` and does not stop the rest.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.watch_mall(watch_id, , rootdir=None)

The stores of one watch.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> import tempfile
>>> mall = watch_mall('demo', rootdir=tempfile.mkdtemp())
>>> sorted(mall)
['digests', 'dropped', 'entities', 'items', 'runs', 'state']
>>> mall['items']['abc'] = {'title': 'Ça marche'}
>>> mall['items']['abc'], list(mall['items'])
({'title': 'Ça marche'}, ['abc'])
```

### keeptabs.whats_new(spec, mall, , since=None, max_items=None, now=None)

The items acquired since `since`, grouped by subtopic, best first.

`since` is a time, or a duration ago (`'3d'`). It defaults to the time of
the last digest, or to a week ago when there has been none. What the last
digest already reported is not reported again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`tools`](keeptabs.tools.md#module-keeptabs.tools)       | The operations of keeptabs, as plain functions: JSON-able arguments in, a JSON-ready dict out.   |
|------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`digest`](keeptabs.digest.md#module-keeptabs.digest)     | Answering "what's new", writing it up, and delivering it.                                        |
| [`engine`](keeptabs.engine.md#module-keeptabs.engine)     | The scheduled run: work out what is due, acquire it, match it, store it.                         |
| [`fetchers`](keeptabs.fetchers.md#module-keeptabs.fetchers) | Acquiring raw items from each kind of source.                                                    |
| [`matching`](keeptabs.matching.md#module-keeptabs.matching) | Deciding whether an item belongs to a watch, and to which part of it.                            |
| [`spec`](keeptabs.spec.md#module-keeptabs.spec)         | The watch specification: what one tracked area is, and how it is watched.                        |
| [`stores`](keeptabs.stores.md#module-keeptabs.stores)     | Where specs and acquired data live, behind `MutableMapping` interfaces.                          |
| [`util`](keeptabs.util.md#module-keeptabs.util)         | Small pure helpers: app directories, durations, timestamps, URL canonicalisation.                |
