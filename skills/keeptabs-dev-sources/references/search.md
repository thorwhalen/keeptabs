# Programmatic web search for a technology-watch package

Research report for the `veille` design, compiled 2026-09-27. Scope: which search backends an agent-driven technology-watch pipeline can call, what they cost, how well they answer "what is new since X", and how to put them behind one seam. Prices change often; every price below carries the date it was checked.

## TL;DR

- The search API market reshuffled in 2025–2026: Bing Search APIs are gone (retired 2025-08-11) [5], Google's Custom Search JSON API is closed to new customers and ends for everyone on 2027-01-01 [4], and Brave dropped its free tier in February 2026 for $5/month of credit [1][2].
- Zero-key options that still work: Google News RSS search URLs [34], the GDELT DOC 2.0 API [31], the `ddgs` metasearch library (formerly `duckduckgo_search`) [8][9], a self-hosted SearXNG [29][30], and the keyless Jina Reader for page text [24]. All are best-effort; only SearXNG is under your control.
- Keyed options with an explicit publication-date window (the property that matters most for "since X"): Tavily `start_date` [12], Exa `startPublishedDate` [14], Perplexity Search `search_after_date_filter` [23], Brave `freshness=YYYY-MM-DDtoYYYY-MM-DD` [3], GDELT `STARTDATETIME` [31].
- LLM built-in search tools (Anthropic $10/1k [17], OpenAI $10/1k plus tokens [18], Gemini $14/1k after 5,000 free/month on Gemini 3 [20]) are good for the interactive "what's new" agent, poor for scheduled bulk acquisition: no date filter, token costs on top, and in Anthropic's case result content comes back encrypted [17].
- Recommendation: default to a zero-key composite (Google News RSS + GDELT + `ddgs`, optionally SearXNG), with Brave or Tavily as the first keyed upgrade and Exa as the semantic-discovery add-on. Details at the end.

## 1. Zero-key options

### Google News RSS search

`https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en` returns an RSS feed of matching news articles; no key, no account [34]. The query accepts `when:1h|12h|7d|1m`, day-precision `after:YYYY-MM-DD` / `before:YYYY-MM-DD`, `site:`, `intitle:`, `allintitle:`, `inurl:`, quoted phrases, `OR` and `-term` [34]. Limits: at most 100 items per call, and item links are Google redirect URLs that need resolving to the publisher URL before dedup [34]. There is no documented API and no published terms for programmatic use, so treat it as an undocumented endpoint that can change without notice. Parse with `feedparser` (6.0.14, 2026-07-30, BSD-2-Clause) [10]; wrappers exist (`gnews` 0.8.2, 2026-06-25; `pygooglenews` 0.1.3, 2024-12-09, stale) [10] but add little over building the URL yourself.

Freshness: the best zero-key date filter available, because `after:` gives a real lower bound.

### GDELT DOC 2.0 API

Free, keyless full-text search over worldwide online news, machine-translated from 65 languages, with a rolling 3-month window [31]. Parameters: `TIMESPAN` (e.g. `24h`, `7d`), `STARTDATETIME`/`ENDDATETIME` in `YYYYMMDDHHMMSS`, `MAXRECORDS` up to 250, `MODE=artlist`, `FORMAT=json|csv|rss` [31]. The rate limit is one request per 5 seconds per IP, enforced strictly: users report that a request at 5.2 s is still rejected and the block then lasts about a minute, with no `Retry-After` header [32]. Shared cloud egress IPs get 429s often [32]. Python client `gdeltdoc` 1.12.0 (2025-04-03, MIT) [10] is usable but slow-moving; calling the endpoint directly with a global throttle is simpler.

Freshness: exact to the second. Coverage: news only, and heavy on general press rather than technical blogs.

### `ddgs` (formerly `duckduckgo_search`)

The `duckduckgo-search` package was renamed to `ddgs`; the old name is frozen at 8.1.1 (2025-07-06) [10] and warns users to migrate [8]. `ddgs` 9.16.0 (2026-08-26, MIT) [8][10] is now a metasearch library: `text()` over bing, brave, duckduckgo, google, grokipedia, mojeek, startpage, yandex, yahoo, wikipedia; `news()` over bing, duckduckgo, yahoo; `timelimit` of `d|w|m|y` [8]. It also ships a REST server and an MCP server [9]. It works by querying the engines' public web front-ends, and the README states it is "for educational purposes only" [9]; expect rate-limit exceptions, breakage when a front-end changes, and a ToS posture you cannot rely on for a commercial deployment.

Freshness: coarse buckets only (day/week/month/year).

### SearXNG (self-hosted)

AGPL-3.0 metasearch engine, very active (about 37.7k stars) [30]. `GET /search?q=...&format=json&time_range=day|month|year&categories=...&pageno=N` [29]. JSON must be enabled in the instance's `settings.yml`, otherwise the request returns 403; many public instances disable it, so run your own (Docker) [29]. It inherits the same upstream-scraping fragility as `ddgs`, but you control the engines, the throttling, and the uptime. AGPL applies to the SearXNG server, not to a Python client calling its HTTP API.

### Jina Reader (and Search)

`r.jina.ai/<url>` turns a page into LLM-friendly text and works without a key at 20 requests/minute (500 RPM with a free key) [24]. The search endpoint `s.jina.ai` is listed as blocked without a key; with a free key (10M free tokens) it runs at 100 RPM, and each search costs at least 10,000 tokens [24]. Use Reader as the zero-key "fetch the article body" step after any search backend, not as the search itself.

## 2. Keyed and paid options

### Brave Search API

Own independent index. Pricing checked 2026-09-27: Search $5 per 1,000 requests, 50 req/s, with $5/month of free credit; Answers $4 per 1,000 plus tokens [1]. The free plan (2,000 queries/month from 2023, raised to 5,000 in August 2025) was removed in February 2026; the $5 credit (about 1,000 queries) requires public attribution and a card on file that is billed for overage with no disclosed cap [2]. `freshness` accepts `pd|pw|pm|py` or an explicit range `2022-04-01to2022-07-30`; `count` max 20, `offset` max 9 [3]. No maintained official Python client (`brave-search` on PyPI last released 2024-04-27) [10]; call the REST endpoint with `httpx`.

### Tavily

Agent-oriented search returning cleaned snippets. Pricing checked 2026-09-27: 1,000 free credits per month, no card, reset on the 1st; pay-as-you-go $0.008/credit; "Project" plan 4,000 credits/month [11]. Basic/fast search costs 1 credit, advanced 2 [12]. Date controls: `time_range` (`day|week|month|year`), `start_date`/`end_date` (`YYYY-MM-DD`), `filter_by_published_date`, `topic=news` (auto-adds `published_date`), `include_domains` up to 300, `max_results` up to 20 [12]. Client `tavily-python` 0.8.4 (2026-09-18, MIT) [10].

### Exa

Neural/semantic index, good for "find pages like this" and for surfacing blog posts and papers that keyword search misses. Pricing checked 2026-09-27: $7 per 1,000 searches for up to 10 results, +$1 per 1,000 additional results; contents $1 per 1,000 pages; $10 of free credit that resets monthly [13]. `startPublishedDate`/`endPublishedDate` (ISO 8601), `category` (`news`, `company`, `publication`, ...), `numResults` up to 100, `includeDomains` up to 1,200, `type` from `instant` to `deep-reasoning` [14]. Client `exa-py` 2.22.2 (2026-09-21, MIT) [10].

### Perplexity Search API and Sonar

The raw Search API costs $5 per 1,000 requests ($1 per 1,000 for "fast"), with no token fees; Sonar (answer generation) adds token pricing and request fees by context size [22]. Date filters are the richest of any provider: `search_after_date_filter`/`search_before_date_filter` (publication date, `%m/%d/%Y`), `last_updated_after_filter`/`last_updated_before_filter`, and `search_recency_filter` (`hour|day|week|month|year`) [23]. Client `perplexityai` 0.43.6 (2026-09-25, Apache-2.0) [10].

### You.com

Web Search API: 100 free calls/day since 2026-07-29, then $5 per 1,000 calls; contents $1 per 1,000 pages [28]. Client `youdotcom` 3.5.0 (2026-09-22, MIT) [10]. The daily free allowance (about 3,000/month) is the most generous recurring free tier among the keyed APIs.

### Serper and SerpApi (Google SERP resellers)

Serper returns Google results as JSON, including news, scholar and patents verticals; 2,500 free queries with no card [15]. SerpApi: 250 searches/month free (50/hour), then $25/month for 1,000, $75 for 5,000, $150 for 15,000; only successful searches count [16]. SerpApi's new client `serpapi` 1.1.2 (2026-09-22, MIT) replaces `google-search-results` (last release 2023-03-10) [10]. Both are third-party scrapers of Google; SerpApi sells a "Legal Shield" only from the $150 plan up [16], which tells you where the legal risk sits.

### Firecrawl search

1,000 free credits/month; search costs 2 credits per 10 results; Hobby $16/month for 5,000 credits; free tier rate limit 10 req/min [25]. Its value is search plus scrape in one call. Client `firecrawl-py` 4.44.0 (2026-09-20, MIT) [10].

### Kagi

Search API at $12 per 1,000 requests, invoiced every 30 days or at $100 [26]; results inherit the account's personalisation (blocked/boosted sites) [27]. The `kagiapi` client has not been released since 2024-05-11 [10]. High quality, low spam, no free tier.

### Google Programmable Search / Custom Search JSON API

Closed to new customers; existing customers must migrate before 2027-01-01 [4]. Terms until then: 100 free queries/day, $5 per 1,000, 10,000/day cap [4]. Google points new users to Vertex AI Search (site search over up to 50 domains) [4], which is not a public-web search API. Do not build on it.

### Bing Search API and Grounding with Bing

The Bing Search APIs were retired on 2025-08-11 and decommissioned [5]. The suggested replacement, Grounding with Bing Search inside Azure AI Agents/Foundry, is priced at $14 per 1,000 transactions (150 TPS, 1M/day) [6]; an earlier price was $35 per 1,000 [7]. Crucially, developers do not get the raw results, only LLM-summarised answers with citations [7]. Useless as an acquisition backend; Bing News is reachable only indirectly (e.g. through `ddgs.news(backend="bing")` [8]).

### NewsAPI.org

The free Developer plan allows 100 requests/day, delays articles by 24 hours, searches only the last month, and forbids staging or production use; the first commercial plan is $449/month [33]. `newsapi-python` last released 2023-03-02 [10]. The 24-hour delay and the licence make it a poor fit; GDELT and Google News RSS cover the same need for free.

## 3. LLM provider built-in search tools

- **Anthropic `web_search`**: $10 per 1,000 searches plus tokens for the retrieved content, which is counted as input on that turn and later turns [17]. Versions `web_search_20250305`, `web_search_20260209` (dynamic filtering: Claude filters results in code before they enter context) and `web_search_20260318` (`response_inclusion`) [17]. Parameters: `max_uses`, `allowed_domains` or `blocked_domains`, `user_location`; no date filter [17]. Each result carries `url`, `title`, `page_age` and an `encrypted_content` blob [17], so you can store the URL list but not the result text. Client `anthropic` 1.8.0 (2026-09-22, MIT) [10].
- **OpenAI `web_search`**: $10 per 1,000 calls plus search-content tokens at model rates; the preview tool on non-reasoning models is $25 per 1,000 with free content tokens [18]. Domain filters up to 100 domains, user location, `search_context_size`; search context capped at 128k tokens [19]. No date filter.
- **Gemini grounding with Google Search**: Gemini 3.x models get 5,000 free search requests/month (shared), then $14 per 1,000; Gemini 2.5 gets 1,500 grounded prompts/day free, then $35 per 1,000 [20]. The ToS impose display requirements for the returned search-suggestions widget, and no time-range parameter is documented [21].

These tools pay off where the agent answers a user's question live ("what happened with X this week?") and can decide how many searches to run. For the scheduled acquisition loop they are the wrong shape: a model call per query, no date window, usage that is hard to cap per topic, and results you may not be allowed to persist verbatim.

## 4. Query generation from a topic spec

A topic spec (`keywords`, `entities`, `sources`, `cadence`, `exclude`) should compile deterministically into a query plan; the LLM enriches the plan occasionally, not on every run.

1. **Keyword expansion, once, cached.** At spec creation (or when the spec changes), ask an LLM for synonyms, acronyms, former names and common misspellings of each keyword and entity, and store the expansion next to the spec. Re-expanding every run costs tokens and makes the query set drift.
2. **Boolean templates.** Compile per backend: `"entity" (release OR launch OR announces OR "now available")`, `"entity" (v2 OR "version 2")`, `intitle:"entity"` for Google News [34]. Keep the templates in config so users can add patterns without code.
3. **Entity + event patterns.** For tracked products, libraries and models: `"<name>" release`, `"<name>" changelog`, `"<name>" benchmark`, `"<name>" vs`. For organisations: `"<org>" launches`, `"<org>" acquires`, `"<org>" paper`.
4. **Date restriction always.** Push `since` down to the backend when it supports an exact window (Tavily, Exa, Perplexity, Brave range, GDELT, Google News `after:`); otherwise use the smallest bucket that covers `now - since` and post-filter on any returned date.
5. **`site:` restriction for known sources.** When the spec lists sources (a vendor blog, a docs changelog), `site:vendor.com/blog` queries are cheap and high-precision; better still, turn them into RSS/sitemap polls in the feed-acquisition layer and stop searching for them.
6. **LLM-generated query sets with diversity.** For open-ended topics, generate N candidate queries, embed them, and keep a maximally diverse subset (greedy max-min distance). This beats N paraphrases of the same query.
7. **Rotation to control cost.** Give each topic a query budget per run (e.g. 4) and a larger pool (e.g. 20). Each run takes the always-on core queries plus a rotating slice of the pool, so every query runs over a cycle of a few days while the per-run cost stays flat.
8. **Yield-based pruning.** Record, per query, how many novel matched URLs it produced. Queries with zero novel yield over K runs drop to a slower rotation; high-yield queries get promoted. This is a cheap multi-armed-bandit and it is where most of the cost saving comes from.
9. **Avoid re-fetching known URLs.** Canonicalise every URL (resolve Google News redirects, strip `utm_*` and fragments, normalise host case) and check a `seen_urls` store before fetching contents. Pay-per-page content APIs (Exa, Jina, Firecrawl, You.com Contents) should only be called for unseen URLs.
10. **Recall vs cost.** Cheap, high-recall zero-key backends for breadth; one paid semantic backend (Exa) for the long tail of blog posts and papers; LLM search only when a user asks a question. Rough monthly cost for 30 topics × 8 queries/day ≈ 7,200 queries, at the prices above: Google News RSS/GDELT/`ddgs` $0; Serper: 2,500 free queries cover the first ten days [15], paid rate not verified from a primary source; You.com ≈ $21 (3,000 free, then $5/1k) [28]; Brave ≈ $31 [1]; Tavily ≈ $50 [11]; Exa ≈ $40 [13]; Anthropic web search ≈ $72 plus tokens [17]. Rotation and pruning typically cut the query count by half or more.

## 5. Seam design: one `search` protocol, pluggable backends

The seam is a callable, injected as a keyword argument with a zero-key default. Backends declare what they can do, so the planner can pick them and so `since` is honoured honestly.

```python
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

DateSupport = Literal["exact", "bucket", "none"]


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    published: datetime | None = None
    backend: str = ""
    raw: Mapping = field(default_factory=dict)


class Searcher(Protocol):
    name: str
    date_support: DateSupport
    cost_per_query: float  # USD, from config, not hardcoded in logic

    def __call__(
        self, query: str, *, since: datetime | None = None, max_results: int = 10
    ) -> Iterable[SearchHit]: ...
```

A zero-key backend, with `since` mapped to the coarsest covering bucket:

```python
def _bucket(since, buckets=(("d", 1), ("w", 7), ("m", 31), ("y", 365))):
    if since is None:
        return None
    days = (datetime.now(timezone.utc) - since).days + 1
    return next((code for code, n in buckets if days <= n), None)


class DdgsNews:
    name, date_support, cost_per_query = "ddgs-news", "bucket", 0.0

    def __call__(self, query, *, since=None, max_results=10):
        from ddgs import DDGS

        for r in DDGS().news(query, timelimit=_bucket(since), max_results=max_results):
            yield SearchHit(
                url=r["url"],
                title=r["title"],
                snippet=r.get("body", ""),
                backend=self.name,
                raw=r,
            )
```

Google News RSS with an exact lower bound:

```python
from urllib.parse import quote_plus
import feedparser


def google_news(
    query, *, since=None, max_results=100, hl="en-US", gl="US", ceid="US:en"
):
    q = f"{query} after:{since.date().isoformat()}" if since else query
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"
    for e in feedparser.parse(url).entries[:max_results]:
        yield SearchHit(
            url=e.link,
            title=e.title,
            published=_to_datetime(e.get("published_parsed")),
            backend="google-news-rss",
        )
```

A keyed backend with an exact window (Brave; key from env, endpoint from config):

```python
import httpx


def brave(
    query,
    *,
    since=None,
    max_results=20,
    api_key,
    endpoint="https://api.search.brave.com/res/v1/web/search",
):
    params = {"q": query, "count": min(max_results, 20)}
    if since:
        params["freshness"] = f"{since.date()}to{datetime.now(timezone.utc).date()}"
    r = httpx.get(endpoint, params=params, headers={"X-Subscription-Token": api_key})
    r.raise_for_status()
    for h in r.json().get("web", {}).get("results", []):
        yield SearchHit(
            url=h["url"],
            title=h["title"],
            snippet=h.get("description", ""),
            backend="brave",
            raw=h,
        )
```

Composition, all as plain functions over the protocol:

- `fan_out(searchers, query, *, since, max_results)`: run several backends, merge by canonical URL, keep the earliest `published`.
- `with_since_postfilter(searcher)`: drops hits whose `published` is known and older than `since`; needed for `bucket` and `none` backends.
- `with_throttle(searcher, min_interval=5.0)`: mandatory for GDELT [32] and wise for `ddgs`.
- `with_seen(searcher, seen: MutableMapping)`: filters URLs already in the `seen_urls` store (a `dol` store on local disk), so downstream content fetching never repeats.
- `with_budget(searcher, ledger: MutableMapping, *, monthly_usd)`: refuses calls once a backend's spend for the month reaches its cap, using `cost_per_query`. This matters for Brave, whose card billing has no disclosed spending cap [2].
- `with_cache(searcher, store)`: key on `(backend, query, since-bucket)` so reruns within a cadence window are free.

Backends register by name through an entry-point group or a plain dict in config (`{"brave": ..., "tavily": ..., "exa": ...}`), so a new provider is one module with no change to the planner. LLM built-in search tools are not `Searcher`s; they belong to the agent layer that answers "what's new" questions over the store.

## 6. Comparison table

Prices checked 2026-09-27; see references for the date each was read.

| Backend | Key? | Free allowance | Paid price | Date filter | Result format | Python client (latest) | Licence / ToS notes |
|---|---|---|---|---|---|---|---|
| Google News RSS | No | Unlimited, undocumented | n/a | Exact day (`after:`), `when:` [34] | RSS, redirect links, ≤100 [34] | `feedparser` 6.0.14, 2026-07 [10] | No published API terms |
| GDELT DOC 2.0 | No | Free, 1 req/5 s/IP [32] | n/a | Exact to the second, 3-month window [31] | JSON/CSV/RSS, ≤250 [31] | `gdeltdoc` 1.12.0, 2025-04 [10] | Open data |
| `ddgs` | No | Free, rate-limited upstream | n/a | Bucket d/w/m/y [8] | dicts (title, href/url, body) | `ddgs` 9.16.0, 2026-08 [10] | MIT; "educational purposes only" [9] |
| SearXNG (self-host) | No | Free, your server | n/a | Bucket day/month/year [29] | JSON/CSV/RSS [29] | plain HTTP | AGPL-3.0 server [30] |
| Jina Reader / Search | Reader no; Search yes | Reader 20 RPM keyless; 10M tokens with key [24] | token-based, ≥10k tokens/search [24] | none | Markdown text | plain HTTP | Commercial API |
| Brave Search | Yes | $5 credit/mo, needs attribution [1][2] | $5/1k [1] | Exact range [3] | JSON, ≤20/page [3] | none maintained (`brave-search` 2024) [10] | Card billed, no cap [2] |
| Tavily | Yes | 1,000 credits/mo [11] | $0.008/credit [11] | Exact `start_date` [12] | JSON, ≤20 [12] | `tavily-python` 0.8.4, 2026-09 [10] | Commercial API |
| Exa | Yes | $10 credit/mo [13] | $7/1k (≤10 results) [13] | Exact `startPublishedDate` [14] | JSON, ≤100 [14] | `exa-py` 2.22.2, 2026-09 [10] | Commercial API |
| Perplexity Search | Yes | none listed | $5/1k [22] | Exact after/before + recency [23] | JSON | `perplexityai` 0.43.6, 2026-09 [10] | Commercial API |
| You.com | Yes | 100 calls/day [28] | $5/1k [28] | not verified | JSON | `youdotcom` 3.5.0, 2026-09 [10] | Commercial API |
| Serper | Yes | 2,500 queries [15] | not verified | not verified | JSON (Google SERP) [15] | plain HTTP | Google-scraping reseller |
| SerpApi | Yes | 250/mo [16] | $25/mo for 1k [16] | not verified | JSON (Google SERP) | `serpapi` 1.1.2, 2026-09 [10] | Legal Shield from $150 plan [16] |
| Firecrawl search | Yes | 1,000 credits/mo [25] | 2 credits/10 results [25] | not verified | JSON + scraped content | `firecrawl-py` 4.44.0, 2026-09 [10] | Commercial API |
| Kagi | Yes | none | $12/1k [26] | not verified | JSON | `kagiapi` 0.2.1, 2024 [10] | Paid account |
| Google CSE JSON | Yes | 100/day (existing only) [4] | $5/1k [4] | n/a | JSON | n/a | Closed to new customers; ends 2027-01-01 [4] |
| Bing Search / Grounding | Yes | none | $14/1k grounding [6] | none | LLM summary, no raw results [7] | n/a | Raw API retired 2025-08-11 [5] |
| NewsAPI.org | Yes | 100 req/day, 24 h delay, dev only [33] | $449/mo [33] | Exact | JSON | `newsapi-python` 0.2.7, 2023 [10] | Free tier forbids production [33] |
| Anthropic web_search | Yes | none | $10/1k + tokens [17] | none | Encrypted content + url/title/page_age [17] | `anthropic` 1.8.0, 2026-09 [10] | Citations must be shown [17] |
| OpenAI web_search | Yes | none | $10/1k + tokens [18] | none | Citations in message [19] | `openai` 3.19.2, 2026-09 [10] | Citations must be clickable [19] |
| Gemini grounding | Yes | 5,000/mo (Gemini 3) [20] | $14/1k [20] | none documented [21] | Grounding metadata [21] | `google-genai` 2.25.0, 2026-09 [10] | Display requirements [21] |

## 7. Recommendation

**Zero-key default (ships in v1, works on install):** a `fan_out` composite of Google News RSS (exact `after:` window, the best free freshness) + GDELT DOC (exact window, global news; throttled to one call per 5+ seconds) + `ddgs.text` (general web, bucketed, post-filtered), wrapped in `with_seen`, `with_cache` and `with_since_postfilter`. Page bodies come from Jina Reader keyless, or a local fetch. If the user runs a SearXNG instance, a `SEARXNG_URL` setting swaps it in for `ddgs` as the general-web backend, which removes most of the fragility. Document plainly that this tier is best-effort and that `ddgs` scrapes public front-ends.

**Stronger optional backends, in the order to add them:**

1. **Brave Search** as the paid general-web backend: independent index, explicit date range, $5/1k, 50 req/s [1][3]. Put a hard `with_budget` cap on it, because the card has no spending cap [2]. **Tavily** is the alternative if a no-card monthly free tier matters more (1,000 credits, exact `start_date`) [11][12].
2. **Exa** for semantic discovery: blog posts, papers and project pages that keyword queries miss, with an exact `startPublishedDate` [13][14]. Run it on the rotating, lower-frequency slice of the query pool.
3. **Perplexity Search** as an alternative general backend when the richest date filtering is wanted (publication and last-updated windows) [22][23].

**Keep LLM built-in search tools (Anthropic, OpenAI, Gemini) in the agent layer**, for live "what's new" questions that the local store cannot answer. Do not use them for scheduled acquisition. Avoid Google CSE, Bing, and the NewsAPI free tier entirely.

## REFERENCES

[1] Brave. Brave Search API pricing. 2026. [api-dashboard.search.brave.com/documentation/pricing](https://api-dashboard.search.brave.com/documentation/pricing)

[2] Implicator.ai. Brave Search API free tier killed, saved card now bills. 2026. [implicator.ai](https://www.implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing/)

[3] Brave. Web search API query parameters (freshness, count, offset). 2026. [api-dashboard.search.brave.com](https://api-dashboard.search.brave.com/app/documentation/web-search/query)

[4] Google for Developers. Custom Search JSON API overview. 2026. [developers.google.com/custom-search/v1/overview](https://developers.google.com/custom-search/v1/overview)

[5] Microsoft Learn. Bing Search APIs retiring on August 11, 2025. 2025. [learn.microsoft.com](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)

[6] Microsoft Bing. Grounding with Bing pricing. 2026. [microsoft.com/en-us/bing/apis/grounding-pricing](https://www.microsoft.com/en-us/bing/apis/grounding-pricing)

[7] PPC Land. Microsoft ends Bing Search APIs on August 11, alternative costs 40-483% more. 2025. [ppc.land](https://ppc.land/microsoft-ends-bing-search-apis-on-august-11-alternative-costs-40-483-more/)

[8] PyPI. ddgs project page. 2026. [pypi.org/project/ddgs](https://pypi.org/project/ddgs/)

[9] deedy5. ddgs repository README. 2026. [github.com/deedy5/ddgs](https://github.com/deedy5/ddgs)

[10] PyPI. Package metadata (JSON API), queried 2026-09-27. 2026. [ddgs](https://pypi.org/pypi/ddgs/json), [duckduckgo-search](https://pypi.org/pypi/duckduckgo-search/json), [tavily-python](https://pypi.org/pypi/tavily-python/json), [exa-py](https://pypi.org/pypi/exa-py/json), [firecrawl-py](https://pypi.org/pypi/firecrawl-py/json), [serpapi](https://pypi.org/pypi/serpapi/json), [google-search-results](https://pypi.org/pypi/google-search-results/json), [perplexityai](https://pypi.org/pypi/perplexityai/json), [youdotcom](https://pypi.org/pypi/youdotcom/json), [brave-search](https://pypi.org/pypi/brave-search/json), [newsapi-python](https://pypi.org/pypi/newsapi-python/json), [gdeltdoc](https://pypi.org/pypi/gdeltdoc/json), [gnews](https://pypi.org/pypi/gnews/json), [pygooglenews](https://pypi.org/pypi/pygooglenews/json), [feedparser](https://pypi.org/pypi/feedparser/json), [kagiapi](https://pypi.org/pypi/kagiapi/json), [anthropic](https://pypi.org/pypi/anthropic/json), [openai](https://pypi.org/pypi/openai/json), [google-genai](https://pypi.org/pypi/google-genai/json)

[11] Tavily. Pricing. 2026. [tavily.com/pricing](https://www.tavily.com/pricing)

[12] Tavily. Search endpoint API reference. 2026. [docs.tavily.com](https://docs.tavily.com/documentation/api-reference/endpoint/search)

[13] Exa. Pricing. 2026. [exa.ai/docs/admin/pricing](https://exa.ai/docs/admin/pricing)

[14] Exa. Search API reference. 2026. [exa.ai/docs/reference/search](https://exa.ai/docs/reference/search)

[15] Serper. Serper: Google Search API. 2026. [serper.dev](https://serper.dev/)

[16] SerpApi. Pricing. 2026. [serpapi.com/pricing](https://serpapi.com/pricing)

[17] Anthropic. Web search tool. 2026. [platform.claude.com](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)

[18] OpenAI. API pricing. 2026. [developers.openai.com/api/docs/pricing](https://developers.openai.com/api/docs/pricing)

[19] OpenAI. Web search tool guide. 2026. [developers.openai.com](https://developers.openai.com/api/docs/guides/tools-web-search)

[20] Google AI for Developers. Gemini API pricing. 2026. [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)

[21] Google AI for Developers. Grounding with Google Search. 2026. [ai.google.dev/gemini-api/docs/google-search](https://ai.google.dev/gemini-api/docs/google-search)

[22] Perplexity. API pricing. 2026. [docs.perplexity.ai](https://docs.perplexity.ai/getting-started/pricing)

[23] Perplexity. Search date and time filters. 2026. [docs.perplexity.ai](https://docs.perplexity.ai/guides/search-date-time-filters)

[24] Jina AI. Reader API. 2026. [jina.ai/reader](https://jina.ai/reader/)

[25] Firecrawl. Pricing. 2026. [firecrawl.dev/pricing](https://www.firecrawl.dev/pricing)

[26] Kagi. API pricing. 2026. [kagi.com/api/pricing](https://kagi.com/api/pricing)

[27] Kagi. Search API documentation. 2026. [help.kagi.com](https://help.kagi.com/kagi/api/search.html)

[28] UsagePricing. You.com adds a 100-calls/day free tier to its Web Search API. 2026. [usagepricing.com](https://www.usagepricing.com/blueprint/activity/you-com-2026-07-29-web-search-free-tier)

[29] SearXNG. Search API. 2026. [docs.searxng.org/dev/search_api.html](https://docs.searxng.org/dev/search_api.html)

[30] SearXNG. searxng repository. 2026. [github.com/searxng/searxng](https://github.com/searxng/searxng)

[31] The GDELT Project. GDELT DOC 2.0 API debuts. 2017. [blog.gdeltproject.org](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)

[32] cyanheads. gdelt-mcp-server issue 44: fixed-interval spacing does not satisfy GDELT's limiter. 2026. [github.com/cyanheads/gdelt-mcp-server/issues/44](https://github.com/cyanheads/gdelt-mcp-server/issues/44)

[33] NewsAPI. Pricing. 2026. [newsapi.org/pricing](https://newsapi.org/pricing)

[34] NewsCatcher. Google News RSS search parameters: the missing docs. 2024. [newscatcherapi.com](https://www.newscatcherapi.com/blog-posts/google-news-rss-search-parameters-the-missing-documentaiton)
