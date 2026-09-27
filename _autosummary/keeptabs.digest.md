# keeptabs.digest

Answering “what’s new”, writing it up, and delivering it.

A digest is data first ([`whats_new()`](#keeptabs.digest.whats_new) returns a JSON-ready dict) and text
second (a summarizer turns that dict into Markdown).

What the items say was written by other people. [`render_markdown()`](#keeptabs.digest.render_markdown) builds
every link from a stored item’s URL and escapes titles and summaries, so fetched
text cannot add a link, a tag or a mention of its own.

### Functions

| [`deliver`](#keeptabs.digest.deliver)(text, channels, \*, title[, dry_run, ...])   | Send a digest to each channel reference, such as `email:me@example.org`, `github:owner/repo#12` (a discussion) or `slack:`.    |
|-------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`escape_text`](#keeptabs.digest.escape_text)(text)                                    | Text that renders as itself, on one line, in Markdown and in HTML: no link, tag, mention, heading or emphasis of its own.      |
| [`make_digest`](#keeptabs.digest.make_digest)(spec, mall, \*[, since, now, ...])       | Build a digest, store it, and deliver it (for real only when `send`).                                                          |
| [`render_markdown`](#keeptabs.digest.render_markdown)(digest)                              | A digest as Markdown, with no model involved.                                                                                  |
| [`scheduled_digest`](#keeptabs.digest.scheduled_digest)(\*[, summarizer, senders])          | The `on_digest_due` callback for [`keeptabs.engine.tick()`](keeptabs.engine.md#keeptabs.engine.tick). |
| [`whats_new`](#keeptabs.digest.whats_new)(spec, mall, \*[, since, max_items, now])   | The items acquired since `since`, grouped by subtopic, best first.                                                             |

### keeptabs.digest.deliver(text, channels, , title, dry_run=True, senders=None)

Send a digest to each channel reference, such as `email:me@example.org`,
`github:owner/repo#12` (a discussion) or `slack:`.

Dry-run by default: a real send reaches people and cannot be unsent. One
failing channel does not stop the others.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### keeptabs.digest.escape_text(text)

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

### keeptabs.digest.make_digest(spec, mall, , since=None, now=None, summarizer=None, send=False, senders=None, mark_reported=None)

Build a digest, store it, and deliver it (for real only when `send`).

`mark_reported` says whether the items count as reported from now on, so the
next digest leaves them out. It defaults to `send`: a dry run changes nothing,
and can be followed by the real send of the same digest. Items are never marked
when a delivery failed, so a digest that did not arrive is sent again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.digest.render_markdown(digest)

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

### keeptabs.digest.scheduled_digest(, summarizer=None, senders=None)

The `on_digest_due` callback for [`keeptabs.engine.tick()`](keeptabs.engine.md#keeptabs.engine.tick).

A period with nothing new is skipped. Otherwise the digest is written to the
`digests` store, and:

- with `digest.auto_send: true`, it is sent, and its items count as reported
  once every channel took it;
- with channels but no `auto_send`, nothing is sent and nothing is marked:
  the items wait for the owner’s `digest --send`;
- with no channel at all, the stored digest is the report.

### keeptabs.digest.whats_new(spec, mall, , since=None, max_items=None, now=None)

The items acquired since `since`, grouped by subtopic, best first.

`since` is a time, or a duration ago (`'3d'`). It defaults to the time of
the last digest, or to a week ago when there has been none. What the last
digest already reported is not reported again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
