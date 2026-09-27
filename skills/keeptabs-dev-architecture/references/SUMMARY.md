# Technology-watch package: research synthesis

Date of research: 2026-09-27. This file combines seven topic reports in this folder: `ingestion-feeds.md`, `ingestion-newsletters.md`, `search.md`, `dedup-matching.md`, `scheduling.md`, `digests-delivery.md` and `prior-art.md`. Each report has its own detailed references, version and licence snapshots, and code sketches. This page gives the recommended stack, the risks and the open questions, citing only the main sources behind each decision.

## 1. The shape, in one paragraph

A tracked subject is a spec file (question served, keywords, exemplar items, sources, cadence). One idempotent `tick` command, woken by whatever the platform provides, works out from stored state which sources are due. It fetches them through one polite HTTP client and normalises everything to items. Each item passes through a layered filter: exact key, then canonical URL or source ID, then near-duplicate text, then entity match, then relevance and novelty. Items are written to `MutableMapping` stores. Entity records are updated as dated observations. A digest is built as structured data and then rendered to one or more channels. "What's new since T" is a diff against stored entity state, not a fresh summarisation. Every stage is a keyword-argument seam whose default needs no API key and no new heavy dependency, and each has a named stronger alternative that exists today.

## 2. Recommended default stack

"Zero-key" means no paid or registered API key. Two defaults still need a credential the user already has or can create for free: an app password for the dedicated inbox, and an existing `gh` login for posting discussions.

| Concern | Zero-key default | Stronger optional alternative | Notes |
|---|---|---|---|
| Feed parsing | `feedparser` 6.0.14 (BSD-2) on bytes from our own HTTP client [1] | `reader` 3.26 (BSD-3), a full engine with scheduling, conditional GET and search, behind a seam because it stores in SQLite [2] | Store `ETag`/`Last-Modified`/next-fetch per feed in the KV store |
| Full text and feed discovery | `trafilatura` 2.2.0 (Apache-2.0), run lazily and only on matched items; `find_feed_urls` for discovery [3] | `readability-lxml` fallback; `feedsearch-crawler` for discovery | Trafilatura ranks at or near the top of its published extraction benchmarks [3] |
| Feedless sites and newsletters as feeds | Kill the Newsletter, RSSHub or RSS-Bridge URLs pasted into specs [14] | Our own IMAP ingestion (below) | Public instances are best-effort |
| Research sources | daily `rss.arxiv.org` feeds; `huggingface_hub` trending models and daily papers; Hacker News Algolia API [53]; Semantic Scholar keyless | `arxiv` lib for keyword back-fill, keeping the 3 s delay [54]; OpenAlex free key [6] | Papers with Code shut down in July 2025, and Hugging Face Trending Papers replaced it [4][5] |
| Code sources | GitHub `releases.atom` per watched repo, plus unauthenticated search | a GitHub token for higher search limits | GitHub has no official trending API |
| Community sources | Reddit `.rss`, slow cadence, treated as fragile | an approved OAuth app with PRAW | New Reddit API apps need pre-approval under its 2025 builder policy [7] |
| Newsletters | IMAP on a dedicated inbox with an app password via `imap-tools` 1.15.0 (Apache-2.0) [12][8]; stdlib `email`, `selectolax`, `markdownify` | Gmail API with the user's own OAuth client in Production mode, using `history.list` cursors [10][11] | One plus-address and label per newsletter; identify the source by `List-Id` [13] |
| Web search | Composite of Google News RSS (`after:` date floor) [20], GDELT DOC (exact window, one call per 5 s) [19] and `ddgs` 9.x [18], behind `search(query, *, since, max_results)` | Brave ($5 per 1k, exact date range) [17] or Tavily (free monthly credits) [21]; Exa for semantic discovery [22]; self-hosted SearXNG replaces `ddgs` | LLM built-in search stays in the interactive agent layer [23] |
| URL and ID canonicalisation | Own `source_key()` extractors for arXiv, GitHub and Hugging Face, then `w3lib` with a tracking-parameter list kept as data [24] | `courlan` or `url-normalize`; adopting `rel=canonical` | Item ID = hash of source key; the feed guid is only a secondary index |
| Near-duplicates | `model2vec` static embeddings with brute-force cosine over a rolling window (threshold about 0.92, to calibrate) [25] | `fastembed` bge-small (ONNX); `datasketch` MinHash-LSH for long bodies | CPU-only is enough at ≤ ~5k items/day |
| Entity matching | Source-ID hits, then `pyahocorasick` over aliases [26], `rapidfuzz` spans [27], then embedding top-k | Cheap-LLM adjudication (`entity \| NEW \| IRRELEVANT`), only within an ambiguity band | New-entity candidates accumulate in their own store |
| Relevance and novelty | `bm25s` against spec keywords [28], plus cosine to a feedback-updated profile, plus novelty (1 − nearest-neighbour similarity) | LLM rubric grading for borderline items; rerankers | Exemplar items beat keywords as a profile seed |
| Story clustering | Single-pass threshold clustering with an entity-overlap boost | Nightly HDBSCAN; BERTopic for digest themes | |
| Scheduling | One idempotent `<pkg> tick` with due-ness from stored state and a non-blocking `filelock` lock [29] | `<pkg> schedule install` generating launchd `StartCalendarInterval` [30] or a systemd timer with `Persistent=true` [31]; GitHub Actions for public-only sources [32] | Miniflux-style adaptive intervals [33]; no daemon in v1; APScheduler 4 is still alpha [34] |
| Digest generation | No-LLM grouped digest: sections for new entities, updates and top stories, built as a `Digest` data object | LLM seam `complete(prompt, schema)` defaulting to `llm` (Apache-2.0) [38]; Anthropic adapter for Batch (50% off) [37] and structured outputs [35] | The LLM cites item IDs only, as an `enum` in the schema; code resolves IDs to URLs [35][36] |
| Delivery | `channel="files"` writes Markdown, HTML, Atom and JSON Feed; `channel="github"` uses `gh api graphql` `createDiscussion` [40] | SMTP with an app password; Slack incoming webhook [41]; Resend (3,000 emails a month free) [42]; Apprise | Avoid `litellm` as a hard dependency (a PyPI compromise in March 2026) [39] |

## 3. Cross-cutting design decisions the reports converge on

- **Seams are keyword arguments with strong defaults.** Every layer has a keyword argument whose replacement already exists: `fetcher=`, `feed_backend=`, `mail_source=`, `search=`, `canonicalizer=`, `embedder=`, `linker=`, `adjudicator=None`, `clusterer=`, `complete=`, `channel=`, `budget=`. See each report's recommendation section.
- **State is data, and it lives in the same store family.** Feed validators, IMAP `(UIDVALIDITY, last UID)` cursors, `SourceState` due-ness and failure counters, seen-URL sets and search caches are all `MutableMapping` records. Items are written before state, which gives at-least-once delivery that content-keyed dedup makes idempotent (`scheduling.md`).
- **Specs are Key Intelligence Topics, not keyword lists.** Each spec states the question it serves, its kind (decision support, early warning or actor profile) and its audience [44], in the service-commitment spirit of AFNOR XP X50-053 [47]. It also carries a small exemplar set of known-relevant items.
- **Keep evidence, signal and interpretation apart.** Each evidence item carries an Admiralty-style grade: source reliability A–F on the source record, information credibility 1–6 on the item [46]. Entity records keep observations separate from interpretation, following Hiltunen's sign, issue and interpretation split [45]. They also keep a radar ring with dated moves, following Thoughtworks' Adopt, Trial, Assess and Caution rings as of Vol. 34 [43].
- **"What's new" is a diff against stored entity records.** The LLM digest tools surveyed (GPT Researcher [48], smol.ai AINews [49]) regenerate from scratch each run. Tools that watch state (changedetection.io [50], Huginn [51]) do not model entities. Persisted entity records are the gap this package fills, and they make digests cheap and repeatable.
- **Close the loop.** Mutes and ratings change the next run's ranking, as in Feedly AI's trainable topic models [52]. Ring moves and interpretations are suggestions a human reviews, never silent edits.

## 4. What changed in 2025–2026 (landmines found during research)

- Bing Search APIs were retired on 2025-08-11 [15]. Google's Custom Search JSON API is closed to new customers and ends for everyone on 2027-01-01 [16]. Brave dropped its free tier in early 2026 in favour of metered billing with monthly credit [17].
- `duckduckgo_search` is now `ddgs` [18].
- Papers with Code is gone, and its domain redirects to Hugging Face Trending Papers [4][5].
- OpenAlex has required a (free) API key since 13 Feb 2026, and the old `mailto` polite pool is deprecated [6].
- New Reddit API apps need pre-approval [7].
- Google ended plain-password IMAP but still accepts app passwords once 2-Step Verification is on [9][8]. Gmail read scopes are restricted: shipping a shared OAuth client would trigger a security assessment [10], and a consent screen left in Testing mode makes refresh tokens expire after 7 days [11].
- `litellm` had malicious versions published to PyPI in March 2026 [39].

## 5. Key design risks

1. **Fragile zero-key search.** `ddgs` scrapes public front ends and Google News RSS parameters are undocumented [18][20]. Mitigations: the composite degrades gracefully, results are cached and post-filtered by date, health is reported in every digest, and SearXNG and Brave or Tavily are one setting away.
2. **Hallucinated links and facts in digests.** Recent measurements still find fabricated references from strong models and research agents [36]. Mitigations: the ID-only citation pattern with an `enum` constraint [35], link verification in code, and the no-LLM digest as a structurally identical fallback.
3. **Cost runaway on paid APIs.** Brave bills a saved card with no provider-side spending cap [17]; LLM grading can creep. Mitigation: the `budget=` seam with per-tick and rolling caps, deferring work instead of overspending (`scheduling.md`).
4. **Newsletter content and terms of service.** Republishing newsletter text in a public digest (for example a public GitHub discussion) raises copyright questions. Following Mailchimp or beehiiv tracking redirects counts as a click. Mitigations: public digests carry titles, links and short excerpts only, redirect-following is opt-in per source, and unsubscribe or confirmation links are never auto-followed (`ingestion-newsletters.md`).
5. **Silent credential decay.** OAuth tokens in Testing mode expire [11]; GitHub Actions schedules are disabled after 60 days of repository inactivity [32]. Mitigations: prefer app-password IMAP and local triggers, and put a source-health section in every digest.
6. **Laptop sleep and missed runs.** cron does not catch up after sleep, but launchd calendar jobs run once on wake [30] and systemd timers with `Persistent=true` run missed jobs at the next boot [31]. Because due-ness is computed from state, any trigger is safe.
7. **Entity-model drift.** Alias lists grow, entities split and merge, and new-entity candidates pile up. Keep a candidate store with human or LLM review, and keep `splink`-style merging as a later seam, not a v1 feature (`dedup-matching.md`).
8. **Supply-chain and weight creep.** Pin `huggingface_hub` (2.0.0 shipped 2026-09-24), keep heavy libraries (torch, spaCy, BERTopic, litellm) out of core dependencies, and put them behind optional extras [39].

## 6. Open questions for the owner

1. **Spec format and schema.** YAML or TOML? Are entities global (shared across subjects) or scoped per subject? The prior-art report argues for global entities with a `subjects` field.
2. **Radar semantics.** Adopt the Thoughtworks rings (with `Caution`) as defaults, or make ring vocabularies purely per-subject? Export BYOR JSON in v1 or later?
3. **Default LLM route.** `llm` as the provider-agnostic default, or a native Anthropic adapter first because of Batch, caching, Citations and structured outputs [35][37][38]? Should the default run make any LLM call at all?
4. **Which mailbox.** A dedicated Gmail with an app password (simplest), or a provider-neutral route such as Fastmail JMAP or a Cloudflare Email Worker writing raw MIME into a store?
5. **Public versus private digests.** Which channels may carry excerpts of subscribed content? Is the GitHub discussion target a private repository by default?
6. **First paid search backend.** Brave (independent index, card with no cap) or Tavily (free monthly credits, no card)? What default monthly budget, and should zero be the default?
7. **Feed backend.** Own `feedparser` plus a KV-state loop (full control, one storage model), or `reader` as the engine (mature adaptive updates, but a second SQLite store to mirror)?
8. **Multi-machine operation.** If the same subjects run on a laptop and a server, what prevents double fetching? A shared lock is out of scope for local disk. Options include a single designated runner, or `portalocker` with Redis.
9. **Human review surface.** Where does the user approve ring moves, entity merges and new-entity candidates: in the digest itself (reply or reaction), through a CLI, or through the agent?

## REFERENCES

[1] feedparser developers. Changelog, feedparser documentation. 2026. [feedparser changelog](https://feedparser.readthedocs.io/en/latest/changelog/)
[2] lemon24. reader documentation. 2026. [reader docs](https://reader.readthedocs.io/en/latest/)
[3] Barbaresi A. Benchmarks and evaluation, Trafilatura 2.2.0 documentation. 2026. [trafilatura evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html)
[4] HyperAI. Paper With Code Shuts Down. 2025. [hyper.ai/en/news/42900](https://hyper.ai/en/news/42900)
[5] Hugging Face. Changelog: Trending Papers. 2025. [huggingface.co/changelog/trending-papers](https://huggingface.co/changelog/trending-papers)
[6] OpenAlex. Deprecations reference. 2026. [help.openalex.org/api/deprecations](https://help.openalex.org/api/deprecations/)
[7] Reddit. Responsible Builder Policy. 2025. [support.reddithelp.com](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
[8] Google. Sign in with app passwords (Google Account Help). 2026. [support.google.com](https://support.google.com/accounts/answer/185833?hl=en)
[9] Google. Transition from less secure apps to OAuth (Google Workspace Admin Help). 2024. [knowledge.workspace.google.com](https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth)
[10] Google. Restricted scope verification. 2026. [developers.google.com](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
[11] ko-hi (DEV Community). Google's OAuth 'Testing' mode expires refresh tokens in 7 days. Publish the consent screen before you schedule anything. 2026. [dev.to](https://dev.to/ko-hi/googles-oauth-testing-mode-expires-refresh-tokens-in-7-days-publish-the-consent-screen-before-24hm)
[12] PyPI. imap-tools 1.15.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/imap-tools/json)
[13] Chandhok R, Wenger G. RFC 2919: List-Id: A Structured Field and Namespace for the Identification of Mailing Lists. 2001. [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc2919.html)
[14] Facchinetti L. Kill the Newsletter!. 2026. [kill-the-newsletter.com](https://kill-the-newsletter.com/)
[15] Microsoft Learn. Bing Search APIs retiring on August 11, 2025. 2025. [learn.microsoft.com](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)
[16] Google for Developers. Custom Search JSON API overview. 2026. [developers.google.com/custom-search/v1/overview](https://developers.google.com/custom-search/v1/overview)
[17] Implicator.ai. Brave Search API free tier killed, saved card now bills. 2026. [implicator.ai](https://www.implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing/)
[18] deedy5. ddgs repository README. 2026. [github.com/deedy5/ddgs](https://github.com/deedy5/ddgs)
[19] The GDELT Project. GDELT DOC 2.0 API debuts. 2017. [blog.gdeltproject.org](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
[20] NewsCatcher. Google News RSS search parameters: the missing docs. 2024. [newscatcherapi.com](https://www.newscatcherapi.com/blog-posts/google-news-rss-search-parameters-the-missing-documentaiton)
[21] Tavily. Pricing. 2026. [tavily.com/pricing](https://www.tavily.com/pricing)
[22] Exa. Search API reference. 2026. [exa.ai/docs/reference/search](https://exa.ai/docs/reference/search)
[23] Anthropic. Web search tool. 2026. [platform.claude.com](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
[24] PyPI. w3lib. 2026. [pypi.org/project/w3lib](https://pypi.org/project/w3lib/)
[25] PyPI. model2vec. 2026. [pypi.org/project/model2vec](https://pypi.org/project/model2vec/)
[26] PyPI. pyahocorasick. 2026. [pypi.org/project/pyahocorasick](https://pypi.org/project/pyahocorasick/)
[27] PyPI. rapidfuzz. 2026. [pypi.org/project/rapidfuzz](https://pypi.org/project/rapidfuzz/)
[28] PyPI. bm25s. 2026. [pypi.org/project/bm25s](https://pypi.org/project/bm25s/)
[29] tox-dev. filelock documentation. 2026. [py-filelock.readthedocs.io](https://py-filelock.readthedocs.io/en/latest/)
[30] launchd.plist(5) manual page (mirror). [leancrew.com/all-this/man/man5/launchd.plist.html](https://leancrew.com/all-this/man/man5/launchd.plist.html)
[31] systemd project. systemd.timer(5) manual page (Arch Linux mirror). 2026. [man.archlinux.org/man/systemd.timer.5](https://man.archlinux.org/man/systemd.timer.5)
[32] GitHub. Events that trigger workflows: schedule. 2026. [docs.github.com](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
[33] Miniflux. Configuration parameters. 2026. [miniflux.app/docs/configuration.html](https://miniflux.app/docs/configuration.html)
[34] PyPI. APScheduler release history (JSON API). 2026. [pypi.org/pypi/APScheduler/json](https://pypi.org/pypi/APScheduler/json)
[35] Anthropic. Structured outputs. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
[36] Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents. 2026. [arXiv:2604.03173](https://arxiv.org/html/2604.03173v1)
[37] Anthropic. Batch processing. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
[38] Willison S. llm on PyPI. 2026. [pypi.org/project/llm](https://pypi.org/project/llm/)
[39] LiteLLM. Security Update: Suspected Supply Chain Incident. 2026. [docs.litellm.ai](https://docs.litellm.ai/blog/security-update-march-2026)
[40] GitHub. Using the GraphQL API for Discussions. 2026. [docs.github.com](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions)
[41] Slack. Sending messages using incoming webhooks. 2026. [docs.slack.dev](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks)
[42] Resend. What are Resend account quotas and limits? 2026. [resend.com](https://resend.com/docs/knowledge-base/account-quotas-and-limits)
[43] Thoughtworks. Technology Radar, Vol. 34. 2026. [thoughtworks.com/radar](https://www.thoughtworks.com/en-us/radar)
[44] Herring JP. Key intelligence topics: a process to identify and define intelligence needs. Competitive Intelligence Review. 1999. [onlinelibrary.wiley.com](https://onlinelibrary.wiley.com/doi/abs/10.1002/(SICI)1520-6386(199932)10:2%3C4::AID-CIR3%3E3.0.CO;2-C)
[45] Hiltunen E. The future sign and its three dimensions. Futures. 2008. [sciencedirect.com](https://www.sciencedirect.com/science/article/abs/pii/S0016328707001085)
[46] Wikipedia. Admiralty code. 2026. [en.wikipedia.org](https://en.wikipedia.org/wiki/Admiralty_code)
[47] AFNOR. XP X50-053: Prestations de veille et prestations de mise en place d'un système de veille. 1998. [boutique.afnor.org](https://www.boutique.afnor.org/en-gb/standard/xp-x50053/watch-services-watch-services-and-watch-system-introduction-services/fa047502/15855)
[48] Elovic A, et al. GPT Researcher. 2026. [github.com/assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher)
[49] smol.ai. AINews. 2026. [news.smol.ai](https://news.smol.ai/)
[50] dgtlmoon. changedetection.io. 2026. [github.com/dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io)
[51] Huginn contributors. huginn/huginn: Create agents that monitor and act on your behalf. 2026. [github.com/huginn/huginn](https://github.com/huginn/huginn)
[52] Feedly. Track specific topics and trends with Feedly AI. n.d. [feedly.com](https://feedly.com/new-features/posts/track-specific-topics-and-trends-with-feedly-ai)
[53] Algolia. HN Search API. [hn.algolia.com/api](https://hn.algolia.com/api)
[54] arXiv. Terms of Use for arXiv APIs. [info.arxiv.org/help/api/tou.html](https://info.arxiv.org/help/api/tou.html)
