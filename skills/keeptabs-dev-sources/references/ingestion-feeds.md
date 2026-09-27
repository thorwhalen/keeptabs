# Ingestion from feeds, the open web and source-specific APIs

Research report for the veille package design. Scope: how the scheduled acquisition step gets new items from RSS/Atom/JSON feeds, from plain web pages (full-text extraction), from feed-generating bridges, and from the source APIs a technology watch cares about most (arXiv, GitHub, Hugging Face, Hacker News, Reddit, Semantic Scholar, OpenAlex). Email newsletters are covered in the sibling report `ingestion-newsletters.md`; only the newsletter-to-feed services are touched here. Versions, dates and licenses were checked against PyPI and project pages on 2026-09-27.

## 1. Feed parsing

**feedparser** is still the reference parser. Latest release 6.0.14 (2026-07-30), BSD-2-Clause, Python >= 3.10 [1][2]. The 2026 releases were maintenance: 6.0.13 dropped Python 3.9 and moved from `sgmllib3k` to `feedparser-sgmllib`, 6.0.14 upgraded that dependency [2]. Its documentation lists RSS 0.90 through 2.0, Atom 0.3/1.0, CDF "and JSON feeds" [3], although the changelog does not flag JSON Feed support in any 6.0.x entry [2], so JSON Feed handling should be tested against real feeds before relying on it. Its strengths are tolerance of malformed XML (the `bozo` flag), date normalisation, and built-in sanitising; its weakness is speed and its dated HTTP layer.

**fastfeedparser** (Kagi) is a feedparser-like API on top of lxml, claiming ~25x (27x across 200 test feeds) the speed of feedparser for RSS 2.0, Atom 1.0 and RDF/RSS 1.0 [4]. Latest 0.6.1 (2026-08-04), MIT [1]. It only parses; it does no HTTP or conditional GET [4]. Useful if ingestion ever reaches thousands of feeds per run; at personal-watch scale (tens to hundreds of feeds) parse time is irrelevant compared to network time.

**reader** (lemon24) is not a parser but a complete feed-reader backend: add feeds, update them, store entries in SQLite, full-text search, tags/metadata on feeds and entries, OPML import/export, feed discovery in web pages, and a plugin system [5][6]. Latest 3.26 (2026-06-24), BSD-3-Clause, fully typed, depends on feedparser, requests and SQLite [1][6]. It supports Atom, RSS and JSON feeds [5]. Its update logic is exactly the politeness behaviour one wants (section 3), which makes it the strongest off-the-shelf option. The catch for veille: its storage is SQLite, not a `MutableMapping`, so it would sit behind a seam rather than be the store of record.

**atoma** parses Atom, RSS 2.0, JSON Feed v1 and OPML into typed objects and uses defusedxml for untrusted input [7], but its last PyPI release is 0.0.17 from 2019-07-07 (MIT) [1]. Treat it as unmaintained. **rss-parser** (4.4.1, 2026-08) is GPL-3.0 [1], which is a poor fit for a permissively licensed library.

Rust-backed options exist (e.g. feedparser-rs with Python bindings, covering RSS/Atom/JSON Feed [8]) but add a compiled dependency for speed nobody here needs.

## 2. Feed autodiscovery

The convention is `<link rel="alternate" type="application/rss+xml|application/atom+xml|application/feed+json" href="...">` in the page head; the RSS Board spec requires `rel` to be exactly `alternate` and says relative hrefs resolve against the page URL [9], and the WHATWG documented the same mechanism for HTML [10]. A 30-line implementation with the stdlib `html.parser` (or lxml) plus a fallback probe of common paths (`/feed`, `/rss`, `/atom.xml`, `/index.xml`, `/feed.json`) covers most sites.

Libraries:

- **trafilatura** ships `find_feed_urls` (discover feeds from a page or parse a known feed URL) and `sitemap_search` [11]. Since trafilatura is the recommended extractor anyway (section 4), this is discovery at zero extra dependency cost.
- **feedsearch-crawler** is an asyncio/aiohttp crawler that returns scored `FeedInfo` objects with title, item count, velocity, last-updated, WebSub support, etc. [12]. Actively maintained: 2.1.7 released 2026-09-24, MIT, Python >= 3.12 [1]. The velocity field is directly useful for choosing a polling cadence.
- **reader** also discovers feeds in pages [5].
- `feedsearch` (1.0.12, 2020) and `feedfinder2` (0.0.4, 2016) are abandoned [1].

Discovery is an agent-time operation ("track this blog"), not a scheduled one, so its cost and dependencies matter little; put it behind a `discover_feeds(url, *, strategy=...)` seam.

## 3. Conditional GET and politeness

**Conditional GET.** Store each feed's `ETag` and `Last-Modified` response headers and send them back as `If-None-Match` / `If-Modified-Since`; an unchanged feed returns `304` with no body. feedparser supports this directly: `d = feedparser.parse(url, etag=..., modified=...)`, then read `d.etag`, `d.modified`, `d.status` [13]. Its docs note that clients should support both headers because some servers only send one [13]. reader does this automatically: "If supported by the server, reader uses the ETag and Last-Modified headers to get the entire content of a feed only if it changed" [14]. Both sources probed for this report send validators: arXiv RSS returned an `ETag` and `Cache-Control: max-age=86399`, and GitHub release Atom feeds returned a weak `ETag` [15][16].

**Scheduling that honours the server.** reader's scheduler updates a feed only when due (default interval one hour, configurable globally or per feed via tags) and "if the server responds with any of the Cache-Control max-age, Expires, or Retry-After HTTP headers, `update_feeds(scheduled=True)` will honor them" [14]. That is the behaviour to copy if veille writes its own fetcher.

**What publishers ask for.** Feed operators have started enforcing good behaviour: rachelbythebay rate-limits its feed, supports at most hourly conditional polling, stops serving clients that poll unconditionally, and expects 429s to be honoured [17][18]. A widely cited checklist [19]: poll at a reasonable interval (hourly or slower for blogs, adaptive to posting frequency), always send conditional headers, stop on 304, on 429 double the interval up to a 24-hour cap, send a descriptive `User-Agent` containing a URL, and accept gzip.

**robots.txt.** RFC 9309 governs "automatic clients known as crawlers" and says a cached robots.txt should not be used for more than 24 hours [20]. Fetching a feed a publisher advertises is conventionally not crawling, but full-text extraction of linked articles and HTML scraping (GitHub trending, bridges) is, so check robots.txt with the stdlib `urllib.robotparser` before those fetches.

**Retry-After / 429 / 503.** Honour `Retry-After` (seconds or HTTP date), fall back to exponential backoff, and persist the resulting `next_fetch_after` in the feed-state store so a crash does not reset politeness. GitHub states the same rule for its API: do not retry before `retry-after` seconds, make requests serially, and continuing while rate-limited "may result in the banning of your integration" [21][22].

**HTTP caching libraries.** If fetching is done outside feedparser, `hishel` (RFC 9111 caching for httpx; 1.4.0, 2026-09-16, BSD) or `requests-cache` (1.3.3, 2026-07-03, BSD-2-Clause) handle validators transparently [1]. Both are optional: explicit validator storage in a KV store is a dozen lines and keeps state inspectable by the agent.

A sketch of the recommended shape, where `state` is any `MutableMapping` (a dol store on disk):

```python
import time, httpx, feedparser
from email.utils import parsedate_to_datetime

DFLT_UA = (
    "veille/0.1 (+https://example.org/veille)"  # config, not hardcoded in practice
)


def fetch_feed(url, state, *, client=None, min_interval=3600, max_backoff=86400):
    """Conditional, backoff-aware fetch. Returns parsed feed or None if nothing new."""
    s = dict(state.get(url, {}))
    if time.time() < s.get("next_fetch_after", 0):
        return None
    client = client or httpx.Client(headers={"User-Agent": DFLT_UA}, timeout=30)
    headers = {
        k: v
        for k, v in {
            "If-None-Match": s.get("etag"),
            "If-Modified-Since": s.get("last_modified"),
        }.items()
        if v
    }
    r = client.get(url, headers=headers, follow_redirects=True)
    interval = s.get("interval", min_interval)
    if r.status_code in (429, 503):
        ra = r.headers.get("Retry-After", "")
        wait = (
            int(ra)
            if ra.isdigit()
            else (
                parsedate_to_datetime(ra).timestamp() - time.time()
                if ra
                else interval * 2
            )
        )
        s.update(
            interval=min(interval * 2, max_backoff), next_fetch_after=time.time() + wait
        )
        state[url] = s
        return None
    s["next_fetch_after"] = time.time() + interval
    if r.status_code == 304:
        state[url] = s
        return None
    r.raise_for_status()
    s.update(etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"))
    state[url] = s
    return feedparser.parse(
        r.content,
        response_headers={
            "content-location": str(r.url),
            "content-type": r.headers.get("content-type", ""),
        },
    )
```

Fetching with httpx and handing bytes to feedparser keeps timeouts, redirects, User-Agent and `Retry-After` under veille's control while keeping feedparser's parsing robustness.

## 4. Full-text extraction

Feeds often carry only a summary; matching and "what's new" answers are better on full text. Current libraries, all checked on PyPI [1]:

| Library | Latest | License | Notes |
|---|---|---|---|
| trafilatura | 2.2.0 (2026-07-31) | Apache-2.0 | Text, metadata, comments; outputs txt/markdown/json/xml/TEI; falls back internally to readability and jusText [11] |
| readability-lxml | 0.9 (2026-08-27) | Apache-2.0 | Port of Arc90 readability; `Document(html).summary()`; lxml + cssselect [23] |
| newspaper4k | 0.9.6 (2026-07-19) | MIT (repo says MIT/Apache-2.0) | Maintained fork of newspaper3k; heavier (lxml, optional nltk, playwright, system libs) [24] |
| goose3 | 3.1.22 (2026-07-23) | Apache-2.0 | Precision-oriented |
| jusText | 3.0.2 (2025-02-25) | BSD-2-Clause | Boilerplate removal by paragraph classification |
| resiliparse | 1.0.9 (2026-07-20) | Apache-2.0 | Very fast, compiled, recall-oriented |

**Benchmarks.** Trafilatura's own evaluation (dated 2026-08-04; 990 documents, 2951 text and 2966 boilerplate segments) gives F-scores of trafilatura 2.2.0 0.924, magic-html 0.889, justext 0.862, news-please 0.836, readability-lxml 0.826, resiliparse 0.811, goose3 0.810, newspaper4k 0.801; goose3 has the highest precision (0.936) but low recall (0.714), and trafilatura is also among the faster tools [25]. This is the author's own benchmark, so it is not neutral. On the independent Zyte/Scrapinghub article-extraction benchmark (repository archived 2026-06-24), trafilatura 2.0.0 scores F1 0.958, behind only its Rust and Go ports (0.970, 0.960) and level with readability.js and a Go readability fork (0.947) [26]. The newer WCXB multi-type benchmark (2026) also puts a trafilatura port first (F1 0.859) and notes goose3's low boilerplate contamination but that it misses half of required content [27]. readability-lxml's own README reports F1 0.975 on a 181-page fixture set, second only to Mozilla Readability [23]. The consistent picture: trafilatura is the best single default; readability is the best fallback for article pages; goose3 when precision matters more than completeness.

Extraction is where robots.txt, rate limits per host, and paywalls bite. Keep it lazy (extract when a matched item needs it, not for every feed entry) and cache extracted text keyed by canonical URL.

## 5. Services that turn newsletters or sites into feeds

- **Kill the Newsletter!** gives you an email address plus an Atom feed; mail sent there becomes entries. Entries older than a month are deleted and feeds are size-capped [28]. MIT-licensed TypeScript/Node, self-hostable [29]. Good for a zero-infrastructure start; for a dedicated inbox veille controls, see the newsletters report.
- **RSSHub** is a Node/TypeScript route collection that produces feeds for thousands of sites; AGPL-3.0, Docker self-hosting, very active (about 46k stars) [30]. Call it over HTTP; the AGPL does not reach a Python client that only consumes its output. Prefer a self-hosted instance over the public one for anything scheduled.
- **RSS-Bridge** is a PHP app with about 447 bridges (including a generic CSS-selector bridge), Unlicense, output as Atom, JSON, MRSS and others, self-hostable via Docker [31].

These are best modelled as feed URLs a user can paste into a spec; veille need not know they exist.

## 6. Source-specific APIs

### arXiv

The legacy APIs (the query API, OAI-PMH and RSS) all fall under one rule: "no more than one request every three seconds, and limit requests to a single connection at a time", counted across all machines you control [32]. RSS/Atom feeds live at `https://rss.arxiv.org/rss/<cat>` and `/atom/<cat>`, categories can be combined with `+` (for example `cs.ai+q-bio.NC`, 2000-result cap), and they are updated daily at midnight US Eastern [33]. For a daily watch, one combined RSS fetch per day per category group is the cheapest and politest source. The query API is for keyword or back-fill searches.

The `arxiv` library (lukasschwab) is at 4.0.1 (2026-07-31), MIT [1][34]. Its `Client` defaults to `page_size=100, delay_seconds=3.0, num_retries=3` and uses requests [35], so defaults already respect the three-second rule:

```python
import arxiv

client = arxiv.Client()  # 3 s delay between pages by default
search = arxiv.Search(
    query='cat:cs.CL AND abs:"retrieval augmented"',
    max_results=50,
    sort_by=arxiv.SortCriterion.SubmittedDate,
)
for r in client.results(search):
    print(r.entry_id, r.published, r.title)
```

### GitHub

- **Release feeds**: `https://github.com/<owner>/<repo>/releases.atom` is keyless Atom with an ETag [16]; also `/tags.atom` and `/commits/<branch>.atom`. This is the zero-key way to watch known repositories.
- **REST API**: 60 requests/hour unauthenticated, 5,000/hour with a token [21]. Search is separate: 10 requests/minute unauthenticated, 30/minute authenticated, at most 1,000 results per query; repository search supports `created:`, `pushed:`, `stars:`, `topic:` qualifiers and `sort=stars|forks|updated` [36]. A query like `topic:llm created:>2026-09-20 sort:stars` is a usable "new and rising" signal. Authenticated conditional requests that return 304 do not count against the primary limit [22].
- **Trending**: there is no official API; the REST and GraphQL APIs do not cover the trending page [37]. Options are scraping the server-rendered `github.com/trending` HTML (fragile, check robots.txt) or OSS Insight's public API, which has a trending-repos endpoint, no key in beta, and 600 requests/hour per IP [37][38].

### Hugging Face Hub

`huggingface_hub` 2.0.0 was released 2026-09-24 (Apache-2.0) [1]; being a fresh major version, pin it. In the current source, `list_models(sort=...)` accepts `"created_at"`, `"downloads"`, `"last_modified"`, `"likes"`, `"trending_score"` (same for datasets; Spaces lack downloads) [39]. Papers: `list_daily_papers(date=, week=, month=, submitter=, sort="publishedAt"|"trending", limit=)` and `list_papers(query=)` which hits `/api/papers/search` [39]. The raw endpoints `https://huggingface.co/api/daily_papers` and `https://huggingface.co/api/models?sort=trendingScore` answered without a token when probed [40][41].

```python
from huggingface_hub import HfApi

api = HfApi()
trending = api.list_models(sort="trending_score", limit=20, token=False)
papers = api.list_daily_papers(sort="trending", limit=20, token=False)
```

### Papers with Code: sunset, replaced by Hugging Face Trending Papers

Papers with Code was shut down by Meta on 24-25 July 2025 without notice; the leaderboards are gone and `paperswithcode.com` now redirects to Hugging Face Trending Papers [42][43]. A request made for this report returned a 302 to `https://huggingface.co/papers/trending` [44]. Hugging Face announced Trending Papers on 2025-07-28 as part of Daily Papers, ranked by recent GitHub star activity and linked to code implementations [45]; the launch was framed as a successor built with Meta and Papers with Code [46]. Archived PwC data survives as a frozen GitHub dump, a `pwc-archive` on Hugging Face and older ORKG imports; CodeSOTA positions itself as a leaderboard successor [43]. For veille: drop PwC as a source; use `list_daily_papers(sort="trending")`.

### Hacker News (Algolia)

`https://hn.algolia.com/api/v1/search` (relevance) and `/search_by_date` (recency) are keyless, with `tags=` (story, comment, show_hn, ask_hn, front_page, author_X), `numericFilters=` (`created_at_i>...`, `points>100`) and `hitsPerPage` [47][48]. Reported courtesy budget is about 10,000 requests/hour per IP, with a hard 1,000-hits-per-query cap, so paginate by time windows [48][49]. The `algolia/hn-search` application repository was archived in February 2026 [50], but the API still answered on 2026-09-27 [51]. Treat it as useful but unsupported and keep the official Firebase HN API as a fallback.

### Reddit

Reddit's Responsible Builder Policy (November 2025) ended self-service API keys: all new OAuth apps need manual pre-approval, and commercial access is negotiated [52][53][54]. Third-party reports say the unauthenticated `.json` endpoints return 403 since 30 May 2026 [53]. That matches a probe for this report (`/r/MachineLearning/new.json`: 403), while `/r/MachineLearning/.rss` still returned `200 application/atom+xml` [55]. PRAW is maintained (8.0.3, 2026-08-12, BSD) [1] but only useful with an approved app. Zero-key default: subreddit `.rss` feeds, polled slowly with a descriptive User-Agent. Expect this to break without notice.

### Semantic Scholar

Most endpoints work without a key but share a pool of 1,000 requests/second across all unauthenticated users (so 429s at busy times); keys are free by request, with an introductory rate of 1 request/second [56]. It offers a recommendations endpoint ("papers similar to a given paper") and free bulk datasets (S2AG, S2ORC) [56]. Python client `semanticscholar` 0.12.0 (2026-03-29, MIT) [1]. Recommendations are a natural "more like the ones I starred" feature for later.

### OpenAlex

The email-based "polite pool" is gone: the `mailto` parameter is ignored since February 2026 [57], and API keys have been required since 13 February 2026 [58]. The announcement gives 100 credits/day without a key and 100,000/day with a free key, with list queries costing more than singleton lookups, and paid tiers above that [58]. The pyalex README describes the costs differently (singletons free, lists 1 credit), which suggests the pricing is still moving [59], so do not hardcode it. `pyalex` 0.21 (2026-02-23, MIT) supports `pyalex.config.api_key` and configurable retries on 429/500/503 [1][59]. OpenAlex data is CC0 [59].

## 7. Keyed and paid options (separate list)

- GitHub token: free; 5,000 req/h REST, 30/min search, 304s free [21][22][36].
- Hugging Face token: free; only needed for gated or private content or higher limits (public listings answered keyless [40][41]).
- Semantic Scholar key: free on request; a dedicated 1 RPS rather than a shared pool [56].
- OpenAlex key: free (100k credits/day); paid above that [58].
- Reddit OAuth: pre-approval required; commercial pricing negotiated [52][54].
- Hosted scraping (for example Apify GitHub-trending actors) is paid per result; avoid it [37].

## 8. Recommendation

Architecture: a `Source` strategy per kind (feed, arxiv, github, hf, hn, reddit, s2, openalex) behind one seam, all sharing (a) a single polite HTTP client (descriptive User-Agent from config, gzip, timeouts, per-host minimum interval, `Retry-After` and exponential backoff) and (b) a `MutableMapping` feed-state store holding `etag`, `last_modified`, `interval`, `next_fetch_after`. Nothing below needs a key.

- **Feed parsing.** Default: `feedparser`, fed bytes fetched by veille's own httpx client. Stronger optional: `reader` as a complete acquisition engine (scheduling, conditional GET, Cache-Control/Retry-After, search), mirrored into veille's stores. `fastfeedparser` only if parse speed ever matters.
- **Conditional GET and politeness.** Default: explicit validator storage in the KV store (sketch in section 3), hourly minimum, 429 doubling to a 24 h cap, robots.txt checked for non-feed fetches. Stronger optional: `hishel` for transparent RFC 9111 caching.
- **Autodiscovery.** Default: trafilatura `find_feed_urls` plus a stdlib `<link rel=alternate>` scan. Stronger optional: `feedsearch-crawler`, whose velocity metric can set cadence.
- **Full text.** Default: `trafilatura`, extracted lazily for matched items only. Optional fallback: `readability-lxml`. Avoid newspaper4k unless its NLP extras are wanted.
- **Newsletters and feedless sites.** Default: Kill the Newsletter or self-hosted RSSHub/RSS-Bridge URLs pasted into specs. Stronger: veille's own IMAP inbox (see the newsletters report).
- **arXiv.** Default: daily `rss.arxiv.org` combined-category feeds. Stronger: the `arxiv` lib for keyword and back-fill queries, keeping the 3 s delay.
- **GitHub.** Default: `releases.atom` for watched repos, plus unauthenticated search (10/min) for "new and rising". Stronger: a token for 30/min search and free 304s; OSS Insight for trending.
- **Hugging Face.** Default: `huggingface_hub` with `token=False`, `list_models(sort="trending_score")`, `list_daily_papers(sort="trending")`. This replaces Papers with Code.
- **Hacker News.** Default: Algolia `search_by_date` with `created_at_i` windows. Fallback: the Firebase API.
- **Reddit.** Default: `.rss` endpoints, slow cadence, treated as fragile. Stronger: approved OAuth app plus PRAW.
- **Scholarly metadata.** Default: Semantic Scholar keyless for enrichment and recommendations. Stronger: an OpenAlex free key via pyalex; S2 key for a dedicated rate.

| Concern | Zero-key default | License | Latest | Optional upgrade |
|---|---|---|---|---|
| Parse feeds | feedparser | BSD-2 | 6.0.14 (2026-07) | reader 3.26 (BSD-3) |
| Fetch/cache | httpx + KV validators | BSD-3 | 0.28.1 (2024-12) | hishel 1.4.0 (BSD) |
| Discover feeds | trafilatura `find_feed_urls` | Apache-2.0 | 2.2.0 (2026-07) | feedsearch-crawler 2.1.7 (MIT) |
| Full text | trafilatura | Apache-2.0 | 2.2.0 (2026-07) | readability-lxml 0.9 (Apache-2.0) |
| arXiv | rss.arxiv.org | n/a | daily | arxiv 4.0.1 (MIT) |
| GitHub | releases.atom + search | n/a | n/a | token; OSS Insight |
| HF / papers | huggingface_hub | Apache-2.0 | 2.0.0 (2026-09) | token |
| HN | Algolia API | n/a | n/a | Firebase API |
| Reddit | `.rss` | n/a | n/a | PRAW 8.0.3 + approved app |
| Scholarly | Semantic Scholar | n/a | n/a | OpenAlex key via pyalex 0.21 (MIT) |

## REFERENCES

[1] Python Software Foundation. PyPI JSON API project metadata (feedparser, reader, fastfeedparser, atoma, feedsearch, feedsearch-crawler, feedfinder2, trafilatura, readability-lxml, newspaper4k, goose3, jusText, resiliparse, arxiv, huggingface_hub, praw, semanticscholar, pyalex, httpx, hishel, requests-cache, rss-parser), queried 2026-09-27. 2026. [pypi.org/pypi/feedparser/json](https://pypi.org/pypi/feedparser/json)
[2] feedparser developers. Changelog, feedparser documentation. 2026. [feedparser changelog](https://feedparser.readthedocs.io/en/latest/changelog/)
[3] feedparser developers. Introduction, feedparser documentation. 2026. [feedparser introduction](https://feedparser.readthedocs.io/en/latest/introduction/)
[4] Kagi. fastfeedparser README. 2026. [kagisearch/fastfeedparser](https://github.com/kagisearch/fastfeedparser)
[5] lemon24. reader documentation. 2026. [reader docs](https://reader.readthedocs.io/en/latest/)
[6] lemon24. reader repository. 2026. [lemon24/reader](https://github.com/lemon24/reader)
[7] Le Manchet N. atoma: Atom, RSS and JSON feed parser for Python 3. 2019. [atoma on PyPI](https://pypi.org/project/atoma/0.0.10)
[8] bug-ops. feedparser-rs: RSS/Atom/JSON Feed parser for Rust with Python and Node.js bindings. 2026. [bug-ops/feedparser-rs](https://github.com/bug-ops/feedparser-rs)
[9] RSS Advisory Board. RSS Autodiscovery. [rssboard.org/rss-autodiscovery](https://www.rssboard.org/rss-autodiscovery)
[10] WHATWG. Feed Autodiscovery. 2006. [blog.whatwg.org/feed-autodiscovery](https://blog.whatwg.org/feed-autodiscovery)
[11] Barbaresi A. Trafilatura: usage with Python. 2026. [trafilatura Python usage](https://trafilatura.readthedocs.io/en/latest/usage-python.html)
[12] Beath D. feedsearch-crawler README. 2026. [DBeath/feedsearch-crawler](https://github.com/DBeath/feedsearch-crawler)
[13] feedparser developers. ETag and Last-Modified Headers, feedparser 6.0.14 documentation. 2026. [feedparser http-etag](https://feedparser.readthedocs.io/en/stable/http-etag.html)
[14] lemon24. reader user guide: updating feeds. 2026. [reader guide](https://reader.readthedocs.io/en/latest/guide.html)
[15] arXiv. cs.CL RSS feed (response headers observed 2026-09-27). 2026. [rss.arxiv.org/rss/cs.CL](https://rss.arxiv.org/rss/cs.CL)
[16] GitHub. huggingface/transformers releases Atom feed (response headers observed 2026-09-27). 2026. [releases.atom](https://github.com/huggingface/transformers/releases.atom)
[17] rachelbythebay. Some early results for feed reader behavior monitoring. 2024. [rachelbythebay.com/w/2024/06/11/fsr/](http://rachelbythebay.com/w/2024/06/11/fsr/)
[18] NewsBlur Forum. Rachel By the Bay feed challenge (and not respecting retry-after). [forum.newsblur.com](https://forum.newsblur.com/t/rachel-by-the-bay-feed-challenge-and-excessive-timeouts-probably-not-respecting-retry-after/10710)
[19] Cleeland B. Respectfully Requesting RSS Feeds with Python. [brntn.me](https://brntn.me/blog/respectfully-requesting-rss-feeds/)
[20] Koster M, Illyes G, Zeller H, Sassman L. RFC 9309: Robots Exclusion Protocol. IETF. 2022. [rfc9309](https://www.rfc-editor.org/rfc/rfc9309.html)
[21] GitHub. Rate limits for the REST API. 2026. [docs.github.com rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
[22] GitHub. Best practices for using the REST API. 2026. [docs.github.com best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
[23] buriy. python-readability (readability-lxml) README. 2026. [buriy/python-readability](https://github.com/buriy/python-readability)
[24] Paraschiv A. newspaper4k README. 2026. [AndyTheFactory/newspaper4k](https://github.com/AndyTheFactory/newspaper4k)
[25] Barbaresi A. Benchmarks and evaluation, Trafilatura 2.2.0 documentation. 2026. [trafilatura evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html)
[26] Zyte (Scrapinghub). Article extraction benchmark. 2026. [scrapinghub/article-extraction-benchmark](https://github.com/scrapinghub/article-extraction-benchmark)
[27] WCXB: A Multi-Type Web Content Extraction Benchmark. arXiv:2605.21097. 2026. [arxiv.org/pdf/2605.21097](https://arxiv.org/pdf/2605.21097)
[28] Facchinetti L. Kill the Newsletter!. 2026. [kill-the-newsletter.com](https://kill-the-newsletter.com/)
[29] Facchinetti L. kill-the-newsletter repository. 2026. [leafac/kill-the-newsletter](https://github.com/leafac/kill-the-newsletter)
[30] DIYgod et al. RSSHub repository. 2026. [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub)
[31] RSS-Bridge contributors. RSS-Bridge repository. 2026. [RSS-Bridge/rss-bridge](https://github.com/RSS-Bridge/rss-bridge)
[32] arXiv. Terms of Use for arXiv APIs. [info.arxiv.org/help/api/tou.html](https://info.arxiv.org/help/api/tou.html)
[33] arXiv. RSS/Atom feeds help. [info.arxiv.org/help/rss.html](https://info.arxiv.org/help/rss.html)
[34] Schwab L. arxiv.py README. 2026. [lukasschwab/arxiv.py](https://github.com/lukasschwab/arxiv.py)
[35] Schwab L. arxiv.py source, `arxiv/__init__.py` (Client defaults). 2026. [arxiv/__init__.py](https://raw.githubusercontent.com/lukasschwab/arxiv.py/master/arxiv/__init__.py)
[36] GitHub. REST API endpoints for search. 2026. [docs.github.com search](https://docs.github.com/en/rest/search/search)
[37] GitHub Community. REST API Endpoints for /explore and /trending (discussion 161519); search results on trending alternatives. 2025. [community discussion](https://github.com/orgs/community/discussions/161519)
[38] PingCAP. OSS Insight public API: list trending repos. 2026. [ossinsight.io/docs/api](https://ossinsight.io/docs/api/list-trending-repos)
[39] Hugging Face. huggingface_hub source, `hf_api.py` (ModelSort_T, list_daily_papers, list_papers). 2026. [hf_api.py](https://raw.githubusercontent.com/huggingface/huggingface_hub/main/src/huggingface_hub/hf_api.py)
[40] Hugging Face. Daily papers API endpoint (probed keyless 2026-09-27). 2026. [huggingface.co/api/daily_papers](https://huggingface.co/api/daily_papers)
[41] Hugging Face. Models API sorted by trendingScore (probed keyless 2026-09-27). 2026. [huggingface.co/api/models?sort=trendingScore](https://huggingface.co/api/models?sort=trendingScore)
[42] HyperAI. Paper With Code Shuts Down. 2025. [hyper.ai/en/news/42900](https://hyper.ai/en/news/42900)
[43] CodeSOTA. Papers With Code Alternative: SOTA Leaderboards and Archived Data. 2026. [codesota.com/papers-with-code](https://www.codesota.com/papers-with-code)
[44] Papers with Code. paperswithcode.com root (302 redirect observed 2026-09-27). 2026. [paperswithcode.com](https://paperswithcode.com/)
[45] Hugging Face. Changelog: Trending Papers. 2025. [huggingface.co/changelog/trending-papers](https://huggingface.co/changelog/trending-papers)
[46] Khaliq A. Post announcing Hugging Face Trending Papers as successor to Papers with Code. 2025. [x.com/_akhaliq](https://x.com/_akhaliq/status/1948729112626946080)
[47] Algolia. HN Search API. [hn.algolia.com/api](https://hn.algolia.com/api)
[48] DEV Community. The Hacker News Search API: Free, No-Key, and Surprisingly Powerful. [dev.to](https://dev.to/odeeb/the-hacker-news-search-api-free-no-key-and-surprisingly-powerful-5e8l)
[49] Algolia hn-search. Issue 230: HN Search API limits number of hits to 1000. [algolia/hn-search#230](https://github.com/algolia/hn-search/issues/230)
[50] Algolia. hn-search repository (archived 2026-02-10). 2026. [algolia/hn-search](https://github.com/algolia/hn-search)
[51] Algolia. HN search_by_date endpoint (probed 2026-09-27). 2026. [hn.algolia.com/api/v1/search_by_date](https://hn.algolia.com/api/v1/search_by_date?tags=story&query=llm&hitsPerPage=1)
[52] Reddit. Responsible Builder Policy. 2025. [support.reddithelp.com](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
[53] FetchLayer. Reddit API Shut Down in 2026: What Still Works. 2026. [fetchlayer.dev](https://fetchlayer.dev/blog/reddit-api-closed-2026)
[54] ReplyDaddy. Reddit's 2025 API Crackdown: Pre-Approval Now Required for All Apps. 2025. [replydaddy.com](https://replydaddy.com/blog/reddit-api-pre-approval-2025-personal-projects-crackdown)
[55] Reddit. r/MachineLearning `.rss` endpoint (200 Atom observed 2026-09-27; `new.json` returned 403). 2026. [reddit.com/r/MachineLearning/.rss](https://www.reddit.com/r/MachineLearning/.rss)
[56] Allen Institute for AI. Semantic Scholar API overview. 2026. [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api)
[57] OpenAlex. Deprecations reference. 2026. [help.openalex.org/api/deprecations](https://help.openalex.org/api/deprecations/)
[58] OpenAlex. API keys required starting Feb 13 (and some new endpoints!), openalex-users group. 2026. [groups.google.com/g/openalex-users](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ)
[59] de Bruin J. pyalex README. 2026. [J535D165/pyalex](https://github.com/J535D165/pyalex)
