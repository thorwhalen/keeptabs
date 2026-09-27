# keeptabs

Keep tabs on the subjects you care about: say what to follow, let a scheduled run collect what is new, and ask what changed.

```
pip install keeptabs
```

This is technology watch, also called horizon scanning, and *veille* in French. It is built to be driven by an AI agent: the agent writes the specification with you, the package does the collecting, and an agent answers your questions from what was collected.

## Quick start

```bash
keeptabs init-watch "Generative AI" --example gen-ai --watch-id gen-ai
keeptabs tick
keeptabs whats-new gen-ai --as-text
```

The first command creates a watch from a shipped example. The second fetches every source that is due, keeps what matches, and stores it. The third prints what is new, grouped by subtopic, with links.

In Python:

```python
from keeptabs import tick, whats_new, watch_mall, spec_store, normalize_spec

tick()
spec = normalize_spec(spec_store()["gen-ai"])
mall = watch_mall("gen-ai")  # stores: items, dropped, entities, runs, digests, state
news = whats_new(spec, mall, since="3d")
```

## How it works

A **watch** is one subject you follow. Its specification is a YAML file that starts as a vague idea and gets sharper over time: a scope, subtopics with keywords, named things to track (models, libraries, companies), sources, and how often to report.

A **tick** is one run. It works out which sources are due from their stored state, fetches them, drops what it has already seen, scores each item against the specification, and stores what is relevant. It is safe to run as often as you like, so any scheduler can trigger it.

A **digest** is the answer to "what's new": the items acquired since the last one, grouped by subtopic. It is stored locally, and sent to the channels you chose only if you turned that on.

Everything is stored under `~/.local/share/keeptabs/`, in stores with a dictionary interface:

```
specs/<watch id>.yaml
data/<watch id>/{items,dropped,entities,runs,digests,state}/<key>.json
```

Set `KEEPTABS_ROOTDIR`, or pass `rootdir=`, to put it elsewhere.

## Building a watch

```bash
keeptabs init-watch "Music AI" --intent "real-time music generation and gesture control"
keeptabs add-keywords music-ai "real-time music generation, neural audio synthesis" --subtopic "Real-time generation" --priority high
keeptabs add-entity music-ai "Magenta RealTime" --kind model --aliases "Magenta RT"
keeptabs add-source music-ai arxiv 'cat:cs.SD AND all:"real-time"' --cadence 1d
keeptabs add-source music-ai github_releases magenta/magenta-realtime --keep-all
keeptabs add-source music-ai feed https://example.org/blog/feed.xml --cadence 12h
keeptabs tick --watch music-ai --force
```

| Source kind | Target | Notes |
|---|---|---|
| `feed` | feed URL | RSS, Atom or JSON Feed, fetched conditionally |
| `arxiv` | arXiv query | newest first |
| `github_releases` | `owner/name` | releases of a repository |
| `hackernews` | search words | |
| `news_search` | search words | news articles |
| `email` | sender address | newsletters in a mailbox, read through [correspond](https://github.com/thorwhalen/correspond); needs `pip install 'keeptabs[mail]'` |

Some things only you can do, such as subscribing to a newsletter or providing a key. An agent records them with `keeptabs add-action`, the sources that depend on them are skipped until `keeptabs resolve-action`, and `keeptabs pending` lists what is waiting on you.

## Asking

```bash
keeptabs whats-new music-ai --since 3d --as-text
keeptabs items music-ai --query "latency" --entity magenta-realtime
keeptabs entities music-ai
keeptabs due          # what runs next, what is failing
```

Add `--json` to any command for the full result.

## Scheduling

```bash
keeptabs schedule                 # a launchd entry on macOS, a cron line elsewhere
keeptabs schedule --kind systemd
```

It prints the entry and how to install it. It installs nothing.

## Digests

In the specification:

```yaml
digest:
  cadence: 1w
  channels:
    - email:someone@example.org
    - github:owner/repo#12      # a discussion
    - slack:                    # webhook URL in KEEPTABS_SLACK_WEBHOOK_URL
    - slack:team                # webhook URL in KEEPTABS_SLACK_WEBHOOK_URL_TEAM
  auto_send: false
```

`keeptabs digest <watch>` is a dry run: it shows the digest and what would be sent where, and changes nothing. `keeptabs digest <watch> --send` sends that same digest, and from then on its items count as reported. The scheduled run writes the digest to the local store, and sends it only when `auto_send` is true. Email and GitHub go through `correspond`, so they pass its outbound checks.

What the items say was written by other people. Titles and summaries are escaped in a digest, and every link is built from a stored item's URL.

## Agent skills

Two skills ship with the package, in `keeptabs/data/skills/`:

- `keeptabs-spec`: create and refine a watch with the user.
- `keeptabs-ask`: answer questions from what a watch collected.

## Extending

Each part that you may want to replace is one keyword argument of `tick` or `make_digest`, with a default that works out of the box.

| Argument | Default | Replace it to |
|---|---|---|
| `rootdir=` | `~/.local/share/keeptabs` | keep the local files elsewhere |
| `specs=`, `malls=`, `lock=` | local files, a local file lock | store elsewhere, with any `MutableMapping` |
| `fetchers=`, `http_get=` | standard library HTTP, `feedparser` | add a source kind, or use another HTTP client |
| `matcher=` | whole-word keyword scoring | score with embeddings or a model, detect near-duplicates |
| `summarizer=` | Markdown, no model | write the digest with a model |
| `senders=` | `correspond`, a Slack webhook | add a delivery channel |

A source kind is any name that has a fetcher at run time. A kind of your own says what to fetch in its `target` field:

```python
from keeptabs import tick


def fetch_my_api(source, *, state, http_get):
    reply = http_get(f"https://api.example.org/new?q={source['target']}")
    ...
    return items, state  # items: dicts with at least 'url' and 'title'


tick(fetchers={"my_api": fetch_my_api})  # for sources with kind: my_api
```

A matcher receives the watch's stores, so it can compare an item with what is already there:

```python
def matcher(item, spec, *, mall):
    ...
    return {
        "score": 3.0,
        "subtopics": [],
        "entities": [],
        "matched": [],
        "duplicate_of": None,
    }
```

To keep everything in stores of your own:

```python
tick(specs=my_specs, malls=lambda watch_id: my_stores_for(watch_id), lock=False)
```

The command line and the shipped skills run with what `keeptabs.tools.components` returns, which is the one place to change for another surface.

## What it does not do yet

- It does not discover new things to track by itself: an agent adds them with `add-entity`. A matcher of your own may name new things, which are stored as candidates.
- It matches by keywords. Near-duplicates under different URLs are stored separately.
- An item judged irrelevant is not judged again when the keywords change later. It is kept in the `dropped` store, with its score.
- Newsletter reading keeps one item per message, filtered by sender.
