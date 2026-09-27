"""Acquiring raw items from each kind of source.

A fetcher is a function ``fetch(source, *, state, http_get) -> (items, state)``:

- ``source`` is one normalized source record of a spec,
- ``state`` is what the fetcher stored last time (validators, cursors),
- ``http_get`` is the one door to the network, so tests and other HTTP clients
  replace it with a single argument,
- ``items`` are raw item dicts with at least ``url`` and ``title``.

:data:`DEFAULT_FETCHERS` maps a source kind to its fetcher. Pass your own mapping
to :func:`keeptabs.engine.tick` to add a kind or replace one. A spec may use any
kind that has a fetcher at run time.

Everything a fetcher returns was written by other people: it is data, and it is
escaped again where it is rendered (:mod:`keeptabs.digest`).
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import quote_plus

from keeptabs.util import item_id, to_datetime

USER_AGENT = "keeptabs (+https://github.com/thorwhalen/keeptabs)"
HTTP_TIMEOUT_SECONDS = 30
ARXIV_API = "https://export.arxiv.org/api/query"
HACKERNEWS_API = "https://hn.algolia.com/api/v1/search_by_date"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GITHUB = "https://github.com"

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_LINK_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


@dataclass
class Response:
    """What a fetcher needs from an HTTP exchange."""

    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)


def http_get(
    url: str, *, etag=None, last_modified=None, timeout=HTTP_TIMEOUT_SECONDS
) -> Response:
    """GET a URL politely: identified, and conditional when validators are known."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return Response(
                reply.status,
                reply.read(),
                {k.lower(): v for k, v in reply.headers.items()},
            )
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return Response(304)
        raise


def strip_html(text: str) -> str:
    """Readable text from an HTML fragment, with no tag left in it.

    Entities are decoded before tags are removed, so an escaped tag does not
    come back to life.

    >>> strip_html('<p>Hello&nbsp;<b>world</b></p>')
    'Hello world'
    >>> strip_html('safe &lt;script&gt;alert(1)&lt;/script&gt; text')
    'safe alert(1) text'
    """
    text = _TAG_RE.sub(" ", unescape(_TAG_RE.sub(" ", text or "")))
    return _SPACE_RE.sub(" ", text.replace("\xa0", " ")).strip()


def extract_links(text: str) -> list:
    """The distinct http(s) links in a text, in order of appearance.

    >>> extract_links('see https://a.example/x, and <a href="https://b.example">b</a>')
    ['https://a.example/x', 'https://b.example']
    """
    links = (link.rstrip(".,;") for link in _LINK_RE.findall(text or ""))
    return list(dict.fromkeys(links))


def _conditional_get(url, *, state, http_get):
    response = http_get(
        url, etag=state.get("etag"), last_modified=state.get("last_modified")
    )
    new_state = dict(state)
    if response.status != 304:
        new_state["etag"] = response.headers.get("etag")
        new_state["last_modified"] = response.headers.get("last-modified")
    return response, new_state


def _parse_feed(body: bytes) -> list:
    import feedparser  # imported here so that importing keeptabs stays cheap

    def published(entry):
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed:
            return None
        return "%04d-%02d-%02dT%02d:%02d:%02d+00:00" % tuple(parsed[:6])

    return [
        {
            "url": entry.get("link", ""),
            "title": strip_html(entry.get("title", "")),
            "summary": strip_html(entry.get("summary", ""))[:2000],
            "published": published(entry),
            "author": entry.get("author"),
            "guid": entry.get("id"),
        }
        for entry in feedparser.parse(body).entries
        if entry.get("link")
    ]


def _fetch_feed_url(url, source, *, state, http_get):
    response, new_state = _conditional_get(url, state=state, http_get=http_get)
    if response.status == 304:
        return [], new_state
    return _parse_feed(response.body)[: source["max_items"]], new_state


def fetch_feed(source, *, state, http_get=http_get):
    """An RSS, Atom or JSON feed at ``source['url']``."""
    return _fetch_feed_url(source["url"], source, state=state, http_get=http_get)


def fetch_arxiv(source, *, state, http_get=http_get):
    """The newest arXiv papers matching ``source['query']`` (arXiv query syntax)."""
    url = (
        f"{ARXIV_API}?search_query={quote_plus(source['query'])}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={source['max_items']}"
    )
    return _fetch_feed_url(url, source, state=state, http_get=http_get)


def fetch_github_releases(source, *, state, http_get=http_get):
    """The releases of the repository ``source['repo']`` (``owner/name``)."""
    url = f"{GITHUB}/{source['repo']}/releases.atom"
    items, new_state = _fetch_feed_url(url, source, state=state, http_get=http_get)
    for item in items:
        item["title"] = f"{source['repo']} {item['title']}"
    return items, new_state


def fetch_news_search(source, *, state, http_get=http_get):
    """News articles matching ``source['query']``, through Google News RSS."""
    url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(source['query'])}"
    return _fetch_feed_url(url, source, state=state, http_get=http_get)


def fetch_hackernews(source, *, state, http_get=http_get):
    """The newest Hacker News stories matching ``source['query']``."""
    url = f"{HACKERNEWS_API}?query={quote_plus(source['query'])}&tags=story&hitsPerPage={source['max_items']}"
    response = http_get(url)
    hits = json.loads(response.body).get("hits", [])
    return [
        {
            "url": hit.get("url")
            or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "title": strip_html(hit.get("title") or ""),
            "summary": strip_html(hit.get("story_text") or "")[:2000],
            "published": hit.get("created_at"),
            "author": hit.get("author"),
            "guid": f"hn:{hit['objectID']}",
            "extra": {"points": hit.get("points"), "comments": hit.get("num_comments")},
        }
        for hit in hits
    ], dict(state)


def _author_name(author):
    if not isinstance(author, dict):
        return author
    return (
        author.get("display_name")
        or author.get("name")
        or author.get("handle")
        or author.get("id")
    )


def _read_mail(ref, *, since, limit):
    try:
        from correspond import tools as correspond_tools
    except ImportError as error:
        raise RuntimeError(
            "Email sources read mail through the 'correspond' package. "
            "Install it with: pip install 'keeptabs[mail]', then run `correspond requirements email`."
        ) from error
    return correspond_tools.read(ref, since=since, limit=limit)


def fetch_email(source, *, state, http_get=None, read_mail=_read_mail):
    """Newsletter issues in the inbox, from ``source['sender']`` (all mail if empty).

    Each message becomes one item, carrying the links found in its body. The
    cursor is the time of the newest message seen.
    """
    result = read_mail(
        f"email:{source.get('sender') or ''}",
        since=state.get("since"),
        limit=source["max_items"],
    )
    if isinstance(result, dict) and not result.get("ok", True):
        raise RuntimeError(
            f"Reading mail failed: {result.get('summary') or result.get('error') or result}"
        )
    messages = result.get("messages", []) if isinstance(result, dict) else result
    items = []
    newest = state.get("since")
    for message in messages:
        native = message.get("native") or {}
        body = message.get("body") or message.get("text") or ""
        sent_at = message.get("sent_at")
        subject = strip_html(native.get("subject") or "") or "(no subject)"
        # a message with no id is identified by what it is, not lumped with the others
        message_id = str(message.get("id") or "").strip("<>") or item_id(
            f"{subject}|{sent_at}|{body[:200]}"
        )
        items.append(
            {
                "url": f"mid:{message_id}",
                "title": subject,
                "summary": strip_html(message.get("text") or body)[:2000],
                "published": sent_at,
                "author": _author_name(message.get("author")),
                "guid": message.get("id"),
                "links": extract_links(native.get("html") or body)[:200],
            }
        )
        if sent_at and (newest is None or to_datetime(sent_at) > to_datetime(newest)):
            newest = sent_at
    return items, {**state, "since": newest}


DEFAULT_FETCHERS = {
    "feed": fetch_feed,
    "arxiv": fetch_arxiv,
    "github_releases": fetch_github_releases,
    "hackernews": fetch_hackernews,
    "news_search": fetch_news_search,
    "email": fetch_email,
}
