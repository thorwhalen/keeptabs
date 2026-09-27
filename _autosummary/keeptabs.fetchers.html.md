# keeptabs.fetchers

Acquiring raw items from each kind of source.

A fetcher is a function `fetch(source, *, state, http_get) -> (items, state)`:

- `source` is one normalized source record of a spec,
- `state` is what the fetcher stored last time (validators, cursors),
- `http_get` is the one door to the network, so tests and other HTTP clients
  replace it with a single argument,
- `items` are raw item dicts with at least `url` and `title`.

`DEFAULT_FETCHERS` maps a source kind to its fetcher. Pass your own mapping
to [`keeptabs.engine.tick()`](keeptabs.engine.html.md#keeptabs.engine.tick) to add a kind or replace one. A spec may use any
kind that has a fetcher at run time.

Everything a fetcher returns was written by other people: it is data, and it is
escaped again where it is rendered ([`keeptabs.digest`](keeptabs.digest.html.md#module-keeptabs.digest)).

### Functions

| [`extract_links`](#keeptabs.fetchers.extract_links)(text)                               | The distinct http(s) links in a text, in order of appearance.                |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`fetch_arxiv`](#keeptabs.fetchers.fetch_arxiv)(source, \*, state[, http_get])        | The newest arXiv papers matching `source['query']` (arXiv query syntax).     |
| [`fetch_email`](#keeptabs.fetchers.fetch_email)(source, \*, state[, http_get, ...])   | Newsletter issues in the inbox, from `source['sender']` (all mail if empty). |
| [`fetch_feed`](#keeptabs.fetchers.fetch_feed)(source, \*, state[, http_get])         | An RSS, Atom or JSON feed at `source['url']`.                                |
| [`fetch_github_releases`](#keeptabs.fetchers.fetch_github_releases)(source, \*, state[, ...])   | The releases of the repository `source['repo']` (`owner/name`).              |
| [`fetch_hackernews`](#keeptabs.fetchers.fetch_hackernews)(source, \*, state[, http_get])   | The newest Hacker News stories matching `source['query']`.                   |
| [`fetch_news_search`](#keeptabs.fetchers.fetch_news_search)(source, \*, state[, http_get])  | News articles matching `source['query']`, through Google News RSS.           |
| [`http_get`](#keeptabs.fetchers.http_get)(url, \*[, etag, last_modified, timeout]) | GET a URL politely: identified, and conditional when validators are known.   |
| [`strip_html`](#keeptabs.fetchers.strip_html)(text)                                  | Readable text from an HTML fragment, with no tag left in it.                 |

### Classes

| [`Response`](#keeptabs.fetchers.Response)(status[, body, headers])   | What a fetcher needs from an HTTP exchange.   |
|--------------------------------------------------------------------------------------|-----------------------------------------------|

### *class* keeptabs.fetchers.Response(status, body=b'', headers=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a fetcher needs from an HTTP exchange.

### keeptabs.fetchers.extract_links(text)

The distinct http(s) links in a text, in order of appearance.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

```pycon
>>> extract_links('see https://a.example/x, and <a href="https://b.example">b</a>')
['https://a.example/x', 'https://b.example']
```

### keeptabs.fetchers.fetch_arxiv(source, \*, state, http_get=<function http_get>)

The newest arXiv papers matching `source['query']` (arXiv query syntax).

### keeptabs.fetchers.fetch_email(source, \*, state, http_get=None, read_mail=<function \_read_mail>)

Newsletter issues in the inbox, from `source['sender']` (all mail if empty).

Each message becomes one item, carrying the links found in its body. The
cursor is the time of the newest message seen.

### keeptabs.fetchers.fetch_feed(source, \*, state, http_get=<function http_get>)

An RSS, Atom or JSON feed at `source['url']`.

### keeptabs.fetchers.fetch_github_releases(source, \*, state, http_get=<function http_get>)

The releases of the repository `source['repo']` (`owner/name`).

### keeptabs.fetchers.fetch_hackernews(source, \*, state, http_get=<function http_get>)

The newest Hacker News stories matching `source['query']`.

### keeptabs.fetchers.fetch_news_search(source, \*, state, http_get=<function http_get>)

News articles matching `source['query']`, through Google News RSS.

### keeptabs.fetchers.http_get(url, , etag=None, last_modified=None, timeout=30)

GET a URL politely: identified, and conditional when validators are known.

* **Return type:**
  [`Response`](#keeptabs.fetchers.Response)

### keeptabs.fetchers.strip_html(text)

Readable text from an HTML fragment, with no tag left in it.

Entities are decoded before tags are removed, so an escaped tag does not
come back to life.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> strip_html('<p>Hello&nbsp;<b>world</b></p>')
'Hello world'
>>> strip_html('safe &lt;script&gt;alert(1)&lt;/script&gt; text')
'safe alert(1) text'
```
