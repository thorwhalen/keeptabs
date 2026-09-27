# keeptabs.tools

The operations of keeptabs, as plain functions: JSON-able arguments in, a
JSON-ready dict out.

This module is the single list every surface is built from ([`TOOLS`](#keeptabs.tools.TOOLS)). It
knows nothing about the command line, MCP or HTTP; a wrapper references
`keeptabs.tools:tick` and gets a dict back.

### Module Attributes

| [`TOOLS`](#keeptabs.tools.TOOLS)   | The single list every surface is built from.   |
|----------------------------------------------------------|------------------------------------------------|

### Functions

| [`add_action`](#keeptabs.tools.add_action)(watch_id, action, \*[, why, ...])      | Record something only the human can do (subscribe to a newsletter, provide a key).                                         |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`add_entity`](#keeptabs.tools.add_entity)(watch_id, name, \*[, kind, url, ...])  | Track a named thing (a model, library, company, lab, person, dataset) in a watch.                                          |
| [`add_keywords`](#keeptabs.tools.add_keywords)(watch_id, keywords, \*[, ...])       | Add comma-separated keywords to a watch, or to one of its subtopics (created if missing).                                  |
| [`add_source`](#keeptabs.tools.add_source)(watch_id, kind, target, \*[, ...])     | Add a source to a watch, or replace the one with the same id.                                                              |
| [`components`](#keeptabs.tools.components)([rootdir])                             | What every tool runs with: the stores, the matcher, the summarizer, the senders.                                           |
| [`digest`](#keeptabs.tools.digest)(watch_id, \*[, since, send, ...])          | Write a digest now and deliver it to the watch's channels.                                                                 |
| [`due`](#keeptabs.tools.due)(\*[, rootdir])                                | What the next tick would fetch, and when each other source is next due.                                                    |
| [`edit_watch`](#keeptabs.tools.edit_watch)(watch_id, patch, \*[, rootdir])        | Change top-level fields of a watch.                                                                                        |
| [`entities`](#keeptabs.tools.entities)(watch_id, \*[, rootdir])                 | The tracked things of a watch, with how often and when each was last seen.                                                 |
| [`examples`](#keeptabs.tools.examples)()                                        | The example watch specifications shipped with the package.                                                                 |
| [`init_watch`](#keeptabs.tools.init_watch)(title, \*[, intent, example, ...])     | Create a watch from a vague idea (`title` and `intent`), from a shipped `example`, or from a YAML or JSON `spec_file`.     |
| [`items`](#keeptabs.tools.items)(watch_id, \*[, query, subtopic, ...])       | Search the stored items of a watch: words in the title or summary, a subtopic, an entity, a source, a time.                |
| [`pending`](#keeptabs.tools.pending)(\*[, rootdir])                            | Everything that waits on the human, across all watches.                                                                    |
| [`remove_source`](#keeptabs.tools.remove_source)(watch_id, source_id, \*[, rootdir]) | Remove a source from a watch.                                                                                              |
| [`resolve_action`](#keeptabs.tools.resolve_action)(watch_id, action_id, \*[, ...])    | Mark a human action as done (or dropped), which unblocks the sources that waited on it.                                    |
| [`schedule`](#keeptabs.tools.schedule)(\*[, kind, every_minutes])               | The scheduler entry that runs `keeptabs tick` regularly: a launchd property list (macOS), a cron line, or a systemd timer. |
| [`tick`](#keeptabs.tools.tick)(\*[, watch, force, rootdir])                 | Run everything that is due: fetch, match, store, and write the digests that are due.                                       |
| [`watch`](#keeptabs.tools.watch)(watch_id, \*[, rootdir])                    | Show one watch specification in full.                                                                                      |
| [`watches`](#keeptabs.tools.watches)(\*[, rootdir])                            | List the watches: id, title, number of sources, and how many human actions are open.                                       |
| [`whats_new`](#keeptabs.tools.whats_new)(watch_id, \*[, since, max_items, ...])  | What a watch acquired since `since` (a time, or a duration ago such as 3d; default: since the last digest).                |

### keeptabs.tools.TOOLS *= [<function examples>, <function watches>, <function watch>, <function init_watch>, <function edit_watch>, <function add_source>, <function remove_source>, <function add_keywords>, <function add_entity>, <function add_action>, <function resolve_action>, <function pending>, <function due>, <function tick>, <function whats_new>, <function items>, <function entities>, <function digest>, <function schedule>]*

The single list every surface is built from.

### keeptabs.tools.add_action(watch_id, action, , why='', blocks=None, rootdir=None)

Record something only the human can do (subscribe to a newsletter, provide a key). `blocks` is a comma-separated list of source ids that must not run until it is done.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.add_entity(watch_id, name, , kind='thing', url=None, aliases=None, note=None, rootdir=None)

Track a named thing (a model, library, company, lab, person, dataset) in a watch. Items that mention it, or one of its comma-separated `aliases`, are linked to it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.add_keywords(watch_id, keywords, , subtopic=None, priority=None, rootdir=None)

Add comma-separated keywords to a watch, or to one of its subtopics (created if missing).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.add_source(watch_id, kind, target, , title=None, cadence=None, keep_all=False, source_id=None, rootdir=None)

Add a source to a watch, or replace the one with the same id. `target` is the feed URL, the search query, the `owner/name` repository or the newsletter sender address, by `kind` (feed, arxiv, github_releases, hackernews, news_search, email; any other kind needs its own fetcher at run time). `keep_all` keeps every item without a keyword match, for a source already dedicated to the topic.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.components(rootdir=None)

What every tool runs with: the stores, the matcher, the summarizer, the senders.

This is the one place to change when a surface should run on other stores or
with a model-based matcher or summarizer: every tool below reads it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.digest(watch_id, , since=None, send=False, mark_reported=False, rootdir=None)

Write a digest now and deliver it to the watch’s channels. Without `send` it is a dry run that changes nothing: show the text and the channels to the user first, because a real send reaches people and cannot be unsent. `mark_reported` counts the items as reported without sending, for a digest that was only read here.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.due(, rootdir=None)

What the next tick would fetch, and when each other source is next due.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.edit_watch(watch_id, patch, , rootdir=None)

Change top-level fields of a watch. `patch` is a JSON object; each key replaces that field (a null removes it). Use it for title, intent, scope, keywords, min_score, digest and enabled.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.entities(watch_id, , rootdir=None)

The tracked things of a watch, with how often and when each was last seen.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.examples()

The example watch specifications shipped with the package.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.init_watch(title, , intent='', example=None, spec_file=None, watch_id=None, overwrite=False, rootdir=None)

Create a watch from a vague idea (`title` and `intent`), from a shipped `example`, or from a YAML or JSON `spec_file`. Refine it afterwards with the add-\* commands or edit-watch.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.items(watch_id, , query=None, subtopic=None, entity=None, source=None, since=None, limit=20, rootdir=None)

Search the stored items of a watch: words in the title or summary, a subtopic, an entity, a source, a time. Newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.pending(, rootdir=None)

Everything that waits on the human, across all watches.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.remove_source(watch_id, source_id, , rootdir=None)

Remove a source from a watch. What it already acquired is kept.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.resolve_action(watch_id, action_id, , status='done', rootdir=None)

Mark a human action as done (or dropped), which unblocks the sources that waited on it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.schedule(, kind=None, every_minutes=30)

The scheduler entry that runs `keeptabs tick` regularly: a launchd property list (macOS), a cron line, or a systemd timer. It is returned, not installed; `install` says how.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.tick(, watch=None, force=False, rootdir=None)

Run everything that is due: fetch, match, store, and write the digests that are due. Safe to run as often as you like; this is what the scheduler calls. `watch` limits it to comma-separated watch ids; `force` ignores the schedule.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.watch(watch_id, , rootdir=None)

Show one watch specification in full.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.watches(, rootdir=None)

List the watches: id, title, number of sources, and how many human actions are open. A watch whose specification cannot be read is listed with its error.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.tools.whats_new(watch_id, , since=None, max_items=None, as_text=False, rootdir=None)

What a watch acquired since `since` (a time, or a duration ago such as 3d; default: since the last digest). Grouped by subtopic, best first. `as_text` adds the Markdown rendering.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
