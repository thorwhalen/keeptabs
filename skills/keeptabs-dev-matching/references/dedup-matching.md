# Deduplication, entity matching, novelty and event clustering for a technology-watch package

Research date: 2026-09-27. Scope: the "is this new, is it a duplicate, what is it about, and which tracked thing does it concern" core of a veille / horizon-scanning package that ingests hundreds to low thousands of items per day from feeds, newsletters, web search, arXiv, GitHub and Hugging Face, and stores everything in `MutableMapping`-style key-value stores on local disk.

## TL;DR

- At this scale (≤ ~5k items/day, a 30-90 day comparison window of ≤ ~500k items) **nothing needs a GPU, a server, or an API key**. Brute-force cosine over a few hundred thousand 256-384-dim vectors is a single NumPy matmul; approximate-nearest-neighbour indexes and LSH are optional accelerators, not requirements.
- Build the pipeline as **five layers of increasing cost**, each one a pluggable strategy (a keyword argument with a strong default): (1) exact key, (2) canonical URL / canonical source ID, (3) near-duplicate text, (4) entity match, (5) relevance and novelty. Each layer only sees what the cheaper layers could not settle.
- Zero-key default stack: `w3lib` + `url-normalize` + a ClearURLs-style param list for URLs; source-specific ID extractors for arXiv / GitHub / Hugging Face; `model2vec` static embeddings (optionally via `semhash`) for near-dups and similarity; `pyahocorasick` + `rapidfuzz` over entity alias lists; `bm25s` + embedding similarity to a topic profile for relevance; single-pass threshold clustering for stories. LLM adjudication (cheap model) is the optional top layer, invoked only for the ambiguous residue.

## 1. Layer 0-1: exact keys, URL canonicalisation and stable item IDs

### 1.1 Why URLs first

The same article reaches a watch system through an RSS item, a newsletter link wrapped in click-tracking, a social share with `utm_*` / `fbclid` parameters, and a search-result link. Collapsing these to one key before doing any text work removes most duplicates at near-zero cost.

### 1.2 Libraries

- **w3lib** (Scrapy project, BSD-3-Clause, 2.4.1 released 2026-03-20) [1][2]. `canonicalize_url(url, keep_blank_values=True, keep_fragments=False, ...)` sorts query arguments by key then value, normalises percent-encoding to upper case, resolves `.`/`..` segments, strips fragments by default and normalises IPv6 hosts [1]. `url_query_cleaner(url, parameterlist, remove=False, ...)` keeps (or with `remove=True` removes) listed query parameters [1]. This is the most battle-tested choice and a light dependency.
- **url-normalize** (MIT, 3.0.1 released 2026-09-22) [3][4]. RFC-oriented normalisation with IDN support, lowercasing of scheme/host, default-port removal and path-segment resolution, plus `filter_params=True` with per-domain allowlists; with the built-in allowlist `utm_source` is removed while e.g. Google's `q` is kept, and on unmapped domains all parameters are dropped unless an allowlist is given [3]. Dropping *all* params on unknown domains is too aggressive for a watch tool (many sites put the article id in the query string), so use it with an explicit denylist strategy or only for scheme/host/IDN normalisation.
- **courlan** (Apache-2.0 since v1, earlier GPLv3+; 1.4.0 released 2026-06-01) [5][6]. `clean_url()` / `normalize_url()` / `check_url()` strip tracking parameters such as `utm_source`, validate domains and can filter by language and content type; it also ships a `UrlStore` for crawl scheduling [5]. It is the companion of the `trafilatura` extractor (Apache-2.0, 2.2.0, 2026-07-31) [7], which is a likely dependency anyway for article text extraction, so courlan comes almost for free.
- **Tracking-parameter lists.** Rather than hard-coding `utm_*`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`, `ref`, keep the list as data. The ClearURLs rules database is a maintained, CI-validated JSON of per-provider tracking parameters, redirections and referral-marketing rules [8]; note its **LGPL-3.0** licence [8] — load it at runtime or at install time as data rather than vendoring it into an MIT package.

### 1.3 rel=canonical and redirects

Publishers declare their preferred URL through a `<link rel="canonical">` element, an HTTP `Link: rel="canonical"` header (for PDFs etc.), sitemaps, or permanent redirects; Google treats `rel=canonical` and redirects as strong signals but only *hints*, not directives [9]. Practical policy: (a) follow redirects once at fetch time (newsletter trackers and `t.co`-style shorteners are resolved this way) and record both the original and final URL; (b) if the fetched HTML declares a canonical URL on the *same registrable domain*, adopt it; if it points cross-domain (syndication), store it as a `canonical_hint` but do not auto-merge, because some sites mis-declare canonicals. Keep every URL ever seen for an item in an `url_index` store mapping `canonical_url -> item_id`, so later sightings of any variant hit layer 1.

### 1.4 Source-specific canonical IDs (better than URLs)

For the high-value sources, the durable key is not a URL but a source identifier:

- **arXiv.** New-style identifiers are `YYMM.NNNNN` (4 digits up to 1412, 5 digits from 1501), old-style are `archive.subclass/YYMMNNN`, and an optional `vN` suffix names a version; an unversioned identifier means the latest version [10]. So `arxiv.org/abs/2310.11244`, `arxiv.org/pdf/2310.11244v2`, `arxiv.org/pdf/2310.11244v2.pdf`, `arxiv.org/html/2310.11244v1` and Hugging Face paper pages that carry the same id all map to key `arxiv:2310.11244`, with the version stored as an attribute. A new version is an *update event* on the same record, not a new item.
- **GitHub.** Lowercase owner and repo (GitHub treats them case-insensitively), strip `www.`, `.git`, trailing slashes and sub-paths like `/tree/main`, `/blob/...`, `/releases/tag/vX` (keep the latter as a sub-entity: a release of the repo). Renamed or transferred repositories keep redirecting for web and git operations, but redirects break if someone later creates a repository at the old name, and Actions calls are not redirected [11]. So resolving to the final `owner/repo` at ingestion time (following the redirect) and storing former names as aliases is safer than trusting old URLs forever.
- **Hugging Face.** Normalise `hf.co` to `huggingface.co` and key models/datasets/spaces as `hf:model:org/name`, `hf:dataset:org/name`, `hf:space:org/name`.

```python
import re
from w3lib.url import canonicalize_url, url_query_cleaner

TRACKING = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
)  # load from config/ClearURLs in practice
ARXIV = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))(v\d+)?",
    re.I,
)
GITHUB = re.compile(r"github\.com/([^/#?]+)/([^/#?]+?)(?:\.git)?(?:[/#?]|$)", re.I)


def source_key(url: str) -> str:
    """Return the most durable key for a URL: a source id if recognised, else a canonical URL."""
    if m := ARXIV.search(url):
        return f"arxiv:{m.group(1)}"
    if m := GITHUB.search(url):
        return f"github:{m.group(1).lower()}/{m.group(2).lower()}"
    url = url_query_cleaner(url, TRACKING, remove=True)
    return canonicalize_url(url)
```

### 1.5 Stable item IDs and feed-guid pitfalls

Use `item_id = hash(source_key)` (e.g. the first 16 hex chars of SHA-256, or `xxhash` — BSD-2-Clause, 4.0.1, 2026-08-17 — for speed [12]) so that the id is a pure function of the canonical key and reproducible across machines and re-ingestions. Do **not** use the RSS `guid` as the primary key: the RSS 2.0 spec leaves uniqueness "up to the source of the feed", `isPermaLink` defaults to `true`, and aggregators only "may" use it to decide novelty [13]. In practice guids get regenerated on CMS migrations, are sometimes non-unique across feeds, and are sometimes plain URLs with tracking params. Store `(feed_id, guid)` as a *secondary* index for fast "already seen in this feed" checks, and fall back to a content hash (normalised title + first 500 chars of body) for items without a usable URL (e.g. newsletter-only blurbs).

## 2. Layer 2: near-duplicate detection

Near-duplicates in a watch stream are syndicated copies, press-release rewrites, and the same announcement reported by several outlets. The first two are *textual* near-dups; the third is really *same event* and belongs to clustering (section 5). Three families of technique:

### 2.1 SimHash

Charikar's SimHash maps a document to a fingerprint such that near-duplicates differ in few bits; Manku, Jain and Das Sarma showed on 8 billion web pages that 64-bit fingerprints with a Hamming-distance threshold of k = 3 work well [14]. Strengths: 8 bytes per item, trivially stored in a key-value store. Weaknesses: it is designed for full web pages; on short texts (titles, 2-sentence summaries) a few changed words flip many bits, so recall is poor. The popular `simhash` package (MIT) last released 2.1.2 in 2022-03 [15] and `simhash-py` last released in 2017 [16] — both effectively unmaintained. SimHash is ~30 lines of code over `xxhash`, so if wanted, implement it in-package rather than taking a stale dependency.

### 2.2 MinHash + LSH

**datasketch** (MIT, 2.0.0 released 2026-07-05, actively maintained) [17][18] provides `MinHash` signatures and `MinHashLSH(threshold=..., num_perm=...)` with `insert(key, m)` / `query(m)`; threshold and `num_perm` are fixed at construction; results are approximate (false positives and negatives); Redis and Cassandra storage backends exist, and `MinHashLSHForest` supports top-k queries [17]. MinHash over word 3-5-gram shingles is the best-performing classic method in the `text-dedup` benchmarks (precision 0.9587 / recall 0.9416 on their test set) [19]. `text-dedup` itself (Apache-2.0, 0.4.1, 2025-12-28) is a set of TOML-configured scripts aimed at LLM pre-training corpora rather than an importable streaming library [19] — good as a reference implementation, wrong shape as a dependency. Reasonable starting point for article bodies: Jaccard threshold 0.7-0.8, `num_perm=128`, 5-word shingles; calibrate on your own data.

### 2.3 Embeddings with a cosine threshold

Embeddings catch paraphrases and rewrites that lexical methods miss, and the same vectors are reused for entity retrieval, relevance and clustering, so one embedding pass amortises over four layers.

- **model2vec** (MIT, 0.9.0, 2026-08-12) [20][21] distils a sentence-transformer into *static* token embeddings: up to 500x faster and ~50x smaller than the source model, numpy-only, CPU-only; recommended models are `potion-base-8M` (English, ~8 MB), `potion-retrieval-32M` and `potion-multilingual-128M` [20]. This is the zero-GPU, near-zero-dependency default.
- **semhash** (MIT, 0.4.2, 2026-09-25) [22][23] wraps model2vec embeddings plus a USearch ANN backend (via `vicinity`) into `SemHash.from_records(...).self_deduplicate()` and cross-set `deduplicate(records, threshold=0.9)`; the authors report ~83 s for 1.8M records on CPU [22]. Ideal for "is this new batch a duplicate of anything in the last 60 days" in a few lines.
- **fastembed** (Apache-2.0, 0.8.1, 2026-09-22, maintained by Qdrant) [24][25] runs ONNX models without PyTorch; the default is `BAAI/bge-small-en-v1.5`, and it also provides sparse (SPLADE++), late-interaction and reranker models [24]. The best "real transformer, still light" option.
- **sentence-transformers** (Apache-2.0, 6.1.0, 2026-09-18) [26] is the reference stack but drags in PyTorch. `all-MiniLM-L6-v2` produces 384-dim vectors and truncates input beyond 256 word pieces (Apache-2.0) [27]; `bge-small-en-v1.5` is 33.4M params, 384-dim, 512-token context, MIT [28].

**Thresholds are model-specific.** BGE's card warns that its similarity scores concentrate in [0.6, 1.0], so "> 0.5" means nothing, and recommends picking a threshold such as 0.8, 0.85 or 0.9 from your own score distribution [28]. Starting points to calibrate (not universal constants): near-duplicate ≥ 0.90-0.95 on title+lead; same-story ≥ 0.75-0.85; embed title + first ~200 words rather than whole articles (MiniLM truncates anyway [27]).

### 2.4 Tradeoffs at this scale

At 1-5k items/day, a 90-day window is at most ~450k vectors; at 256 dims float32 that is ~460 MB, at 30 days and 1k/day just ~30 MB. A new day's batch against the window is one matrix product, so ANN (USearch 2.26.2, Apache-2.0 [29]; faiss-cpu 1.15.1, MIT [30]) is an optimisation to add behind a seam, not a v1 requirement. SimHash/MinHash remain valuable only as a *pre-filter* for long bodies or when you want dedup without loading any model.

```python
import numpy as np
from model2vec import StaticModel

model = StaticModel.from_pretrained("minishlab/potion-base-8M")


def near_dup_of(new_texts, window_vecs, window_ids, *, threshold=0.92):
    """Map each new text to the id of an existing near-duplicate, or None."""
    v = model.encode(new_texts)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    sims = v @ window_vecs.T  # window_vecs pre-normalised
    best = sims.argmax(axis=1)
    return [
        window_ids[j] if sims[i, j] >= threshold else None for i, j in enumerate(best)
    ]
```

## 3. Layer 3: entity resolution — which tracked thing is this item about?

This is *mention-to-entity linking* against a small, curated catalogue (tracked models, companies, libraries, papers), not classic table-to-table record linkage. Treat them as two different problems.

### 3.1 Alias gazetteer (exact multi-pattern)

Each entity spec carries `aliases` (e.g. `["Llama 3.1", "Llama-3.1", "meta-llama/Llama-3.1-8B"]`) plus source ids (`github:...`, `hf:model:...`, `arxiv:...`). Source ids found in item links give a **certain** match (layer 1 already extracted them). For text, build one automaton over normalised aliases:

- **pyahocorasick** (BSD-3-Clause, 2.3.1, 2026-04-27) [31][32]: C implementation of Aho-Corasick; `add_word`, `make_automaton`, `iter` / `iter_long` (longest non-overlapping matches); automata are picklable [31]. Scales to hundreds of thousands of aliases with runtime governed by text length.
- **flashtext** (MIT) is often recommended, but its last release (2.7) is from 2018 [33]; prefer pyahocorasick.
- **spaCy EntityRuler** (spaCy MIT, 3.8.16, 2026-08-24) [34][35]: phrase and token patterns, an `id` field that links many aliases to one entity, and `phrase_matcher_attr="LOWER"` for case-insensitive matching [34]. Worth it only if spaCy is already in the stack (e.g. for NER-based new-entity discovery, 3.4); otherwise it is a heavy dependency for what pyahocorasick does.

Always post-check word boundaries and ambiguity: short aliases ("Phi", "Gemma", "Mamba") need a context guard (co-occurring terms or the source being AI-related) or a mandatory adjudication step.

### 3.2 Fuzzy alias matching

**rapidfuzz** (MIT, 3.14.6, 2026-08-30) [36][37] offers `process.extractOne` / `extract` / `cdist` with scorers `ratio`, `partial_ratio`, `token_set_ratio`, `WRatio`, plus `score_cutoff` and `workers` [36]. Use it on *candidate spans* (capitalised n-grams, code-formatted tokens, repo-like strings) against the alias list with `score_cutoff≈90` to catch "Llama3.1", "LLaMA 3.1 8B" etc. `jellyfish` (MIT, 1.2.1) adds phonetic codes if needed [38].

### 3.3 Probabilistic record linkage (for entity-record merging, not mention linking)

- **splink** (MIT, 4.0.17, 2026-09-03, very active) [39][40]: Fellegi-Sunter model trained unsupervised with EM, term-frequency adjustments, backends DuckDB, Spark, Athena, PostgreSQL, SQLite; about a million records linked on a laptop in about a minute [39]. Right tool for merging *entity records* from several structured sources (e.g. a paper seen via arXiv, Semantic Scholar and a Hugging Face paper page; a company seen in several databases) — overkill for linking a news item to a 200-entity catalogue.
- **dedupe** (MIT) [41][42]: active-learning record linkage by DataMade; the repository is not archived, but the last PyPI release is 3.0.3 (2024-08-15) and the last push is 2025-07 — maintenance has slowed.
- **recordlinkage** (BSD-3-Clause) [43]: last release 0.16 in 2023-07, last push 2024-02 — effectively stale; avoid for new work.

### 3.4 Embedding retrieval + LLM adjudication, and new-entity discovery

For items with no gazetteer hit, or with an ambiguous one: embed the item (already done in layer 2), retrieve the top-k entity *profiles* (name + aliases + one-paragraph description, embedded once), and if the best similarity is in an ambiguous band, ask a cheap LLM to decide among `{entity_id, NEW_ENTITY, IRRELEVANT}` with a short justification. Generative LLMs are competitive entity matchers without task-specific training data and are more robust to unseen entities than fine-tuned PLM matchers [44], which is exactly the situation of a user-curated catalogue.

```python
ADJUDICATE = """Item: {title}\n{lead}\n\nCandidate tracked entities:\n{candidates}\n
Answer JSON: {{"decision": "<entity_id>|NEW_ENTITY|IRRELEVANT", "mention": "<span>", "confidence": 0-1}}"""


def link(item, *, gazetteer, retriever, adjudicator=None, band=(0.55, 0.8)):
    if hits := gazetteer(item):  # certain or near-certain
        return hits
    cands = retriever(item.vec, k=5)  # [(entity_id, sim), ...]
    if not cands or cands[0][1] < band[0]:
        return []  # nothing plausible; still eligible for discovery
    if cands[0][1] >= band[1] or adjudicator is None:
        return [cands[0][0]]
    return adjudicator(ADJUDICATE, item, cands)  # the ONLY paid/slow step
```

**New-entity discovery.** Keep a `candidate_mentions` store: every unmatched salient mention (from `NEW_ENTITY` decisions, spaCy NER, or regexes for repo/model ids) is counted with the items and sources it came from. Promote a candidate to a proposed entity when it crosses a support threshold (e.g. ≥ 3 items from ≥ 2 independent sources within 7 days), and surface the proposal to the agent/user rather than auto-tracking it. Canonical source ids (a new `github:` or `hf:model:` key appearing repeatedly) are the strongest discovery signal.

## 4. Layer 4: relevance and novelty

### 4.1 Novelty = first-story detection

The Topic Detection and Tracking (TDT) programme framed three tasks: story segmentation, detecting the first story about a new event, and tracking subsequent stories given examples [45]. Classic first-story detection scores a document by its distance to its nearest neighbour among past documents; Petrović, Osborne and Lavrenko made this streaming-scale with LSH, an order of magnitude faster at comparable accuracy [46]. For a watch tool: `novelty = 1 - max_cos(item, window)`, computed for free from layer 2's similarity matrix, with the window restricted to items already associated with the same entity or topic when possible ("new *for this topic*").

### 4.2 Topic relevance

Combine three scores, cheapest first:

1. **Lexical**: BM25 of the item against the topic spec's keywords/queries. **bm25s** (MIT, 0.3.11, 2026-08-25) [47][48] is numpy-based, reports hundreds of queries/s where `rank_bm25` does single digits on some benchmarks, and saves/loads (memory-mapped) indexes [47]. `rank_bm25` (Apache-2.0) still works but its last release was 0.2.2 in 2022 [49].
2. **Semantic**: cosine between the item vector and a **topic profile vector** (the embedding of the spec's description plus the centroid of items the user marked relevant).
3. **LLM grading** (optional): a rubric-scored 0-3 relevance grade with one-line reason, only for items whose combined score falls in the uncertain band.

**Feedback loop.** Thumbs up/down update the profile Rocchio-style: `profile ← α·profile + β·mean(liked) − γ·mean(disliked)`, and the stored (item, label) pairs double as a calibration set for the thresholds above and as few-shot examples for the LLM grader.

## 5. Event clustering and story chains

Several distinct items about the same release (the lab's blog post, the arXiv paper, the HF model card, three news write-ups) should be presented as **one story** with sources.

- **Single-pass threshold clustering** (the TDT baseline): for each new item, find the most similar *open* cluster (centroid or max-link within the last N days); join if similarity ≥ τ (e.g. 0.75-0.8 for bge/MiniLM-class models, calibrated), else open a new cluster. Order-dependent but incremental, explainable, O(items × open clusters), and trivially persisted in a key-value store. Boost joins when items share a tracked entity or a canonical source id.
- **HDBSCAN** (BSD-3-Clause; standalone `hdbscan` 0.8.44 [50], and `sklearn.cluster.HDBSCAN` since scikit-learn 1.3 [51]) finds variable-density clusters and labels outliers as noise, but is transductive: scikit-learn's version has no `predict` [51]; the standalone package offers `approximate_predict` against a frozen model and advises periodic re-fitting [52]. Use it for a nightly/weekly batch re-clustering pass that corrects single-pass drift.
- **BERTopic** (MIT, 0.17.4, 2025-12-03, repository active) [53] adds c-TF-IDF topic labels; its online mode uses `partial_fit` with `IncrementalPCA`, `MiniBatchKMeans` and `OnlineCountVectorizer(decay=...)`, with `merge_models` as an alternative [54]. Good for *themes* in a periodic digest ("this month: small reasoning models, agent frameworks"), too coarse and heavy (UMAP, HDBSCAN, torch by default) for per-event story clustering.
- **river DBSTREAM** (river BSD-3-Clause, 0.26.1) [55] is a true online density clusterer (`learn_one` / `predict_one`, `fading_factor` for forgetting) [55]; an option if single-pass proves too brittle, at the cost of less interpretable clusters.
- **Story chains**: link today's cluster to an earlier cluster when their centroids exceed a lower threshold *and* they share a tracked entity (e.g. "model X released" → "model X benchmarks disputed" → "model X v1.1"); store the chain as `previous_cluster_id` on the cluster record so an agent can answer "what happened with X since last month".

## 6. The layered pipeline and its costs

| Layer | Question | Default (zero-key) | Typical cost per item | Resolves |
|---|---|---|---|---|
| 0 Exact | seen this exact key / (feed, guid) / content hash? | dict lookup in a KV store | microseconds | re-polls, re-sends |
| 1 Canonical | same URL or source id? | `w3lib` + param list + arXiv/GitHub/HF extractors; redirect follow at fetch | microseconds (+ one HTTP request if resolving redirects) | tracking-param variants, arXiv versions, pdf vs abs |
| 2 Near-dup | same text? | `model2vec` cosine vs window (optionally `semhash`); MinHash for long bodies | ~0.1 ms embed + one matmul row | syndication, rewrites |
| 3 Entity | which tracked entity? | source-id hits, `pyahocorasick` aliases, `rapidfuzz` spans, embedding retrieval | ~0.1-1 ms | most items |
| 3b Adjudicate | ambiguous entity / new? | cheap LLM, band-limited | 0.2-2 s and fractions of a cent (keyed) | 5-15% residue |
| 4 Relevance + novelty | does the user care, is it new? | `bm25s` + profile cosine + novelty from layer 2 | ~1 ms | ranking, digest inclusion |
| 5 Clustering | same story? | single-pass threshold clusters, nightly HDBSCAN | ~1 ms online; seconds nightly | story grouping, chains |

Timings are order-of-magnitude estimates for CPU, not benchmarks. The key property: layers 0-2 run on everything, 3b and LLM grading run only on items that remain ambiguous, so a day of 2,000 items might send on the order of 100-300 items to an LLM.

Each layer should be a keyword-only strategy argument on the pipeline (e.g. `canonicalizer=`, `embedder=`, `linker=`, `adjudicator=None`, `clusterer=`), with the defaults above, so the keyed alternatives slot in without touching the core.

## 7. Keyed / paid alternatives (optional upgrades)

- **Hosted embeddings** (drop-in for the `embedder` seam): OpenAI, Voyage, Cohere, Jina, Google, Mistral embedding endpoints. Higher quality on long and multilingual text; cost per token, network dependency, and a data-egress consideration for private sources.
- **LLM adjudication and relevance grading**: any small, cheap chat model (Claude Haiku-class, GPT mini-class, Gemini Flash-class) with structured JSON output; or a local model via Ollama / llama.cpp to stay key-free at the cost of latency.
- **Hosted rerankers** (Cohere, Jina, Voyage) for relevance ranking of a candidate list; the key-free equivalent is fastembed's cross-encoder rerankers [24].

## 8. Recommendation

**Default (zero API key, CPU only, light dependencies):**

- *Layer 0-1:* own `source_key()` with regex extractors for arXiv / GitHub / Hugging Face, falling back to `w3lib.url_query_cleaner` + `canonicalize_url` with a tracking-param list kept as data (seeded from ClearURLs at runtime, respecting its LGPL licence). Item id = hash of source key; RSS guid only as a secondary index.
- *Layer 2:* `model2vec` `potion-base-8M` (or `potion-retrieval-32M`) embeddings of title+lead, brute-force cosine against a rolling window, threshold ≈0.92 calibrated on labelled pairs; add `semhash` if the helper saves code. Skip SimHash/MinHash in v1.
- *Layer 3:* source-id hits → `pyahocorasick` gazetteer over aliases → `rapidfuzz` on candidate spans → embedding top-k over entity profiles. Candidate-mention store for new-entity discovery.
- *Layer 4:* `bm25s` against spec keywords + cosine to a feedback-updated profile + novelty from layer 2.
- *Layer 5:* single-pass threshold clustering with entity-overlap boost; story chains via `previous_cluster_id`.

**Stronger optional alternative per layer:**

- Layer 1: `courlan` (already present if `trafilatura` is used) or `url-normalize` for IDN/RFC edge cases; canonical-link adoption from fetched HTML.
- Layer 2: `fastembed` with `bge-small-en-v1.5` (ONNX, no torch) or a hosted embedding API; `datasketch` MinHash-LSH as a model-free pre-filter for long bodies.
- Layer 3: cheap-LLM adjudication in an ambiguity band; `splink` (DuckDB) only for merging structured entity records across sources.
- Layer 4: LLM rubric grading for borderline items; hosted or fastembed rerankers.
- Layer 5: nightly HDBSCAN re-clustering; BERTopic (online mode) for periodic theme labelling in digests.

### Library status snapshot (checked 2026-09-27)

| Library | Role | Latest | Released | License | Verdict |
|---|---|---|---|---|---|
| w3lib [2] | URL canonicalisation | 2.4.1 | 2026-03-20 | BSD-3-Clause | default |
| url-normalize [4] | URL normalisation | 3.0.1 | 2026-09-22 | MIT | optional |
| courlan [6] | URL cleaning/filtering | 1.4.0 | 2026-06-01 | Apache-2.0 | optional |
| xxhash [12] | fast hashing | 4.0.1 | 2026-08-17 | BSD-2-Clause | optional |
| simhash [15] | SimHash | 2.1.2 | 2022-03-03 | MIT | stale; implement in-house if needed |
| datasketch [18] | MinHash/LSH | 2.0.0 | 2026-07-05 | MIT | optional |
| text-dedup [19] | dedup scripts | 0.4.1 | 2025-12-28 | Apache-2.0 | reference only |
| model2vec [21] | static embeddings | 0.9.0 | 2026-08-12 | MIT | default |
| semhash [23] | semantic dedup | 0.4.2 | 2026-09-25 | MIT | optional helper |
| fastembed [25] | ONNX embeddings | 0.8.1 | 2026-09-22 | Apache-2.0 | stronger option |
| sentence-transformers [26] | torch embeddings | 6.1.0 | 2026-09-18 | Apache-2.0 | heavy option |
| usearch [29] / faiss-cpu [30] | ANN | 2.26.2 / 1.15.1 | 2026-08 / 2026-09 | Apache-2.0 / MIT | later, behind a seam |
| pyahocorasick [32] | alias gazetteer | 2.3.1 | 2026-04-27 | BSD-3-Clause | default |
| flashtext [33] | keyword extraction | 2.7 | 2018-02-16 | MIT | unmaintained; avoid |
| rapidfuzz [37] | fuzzy matching | 3.14.6 | 2026-08-30 | MIT | default |
| spaCy [35] | EntityRuler / NER | 3.8.16 | 2026-08-24 | MIT | optional (discovery) |
| splink [40] | probabilistic linkage | 4.0.17 | 2026-09-03 | MIT | optional (record merging) |
| dedupe [42] | active-learning linkage | 3.0.3 | 2024-08-15 | MIT | slowing; not needed |
| recordlinkage [43] | record linkage | 0.16 | 2023-07-20 | BSD-3-Clause | stale; avoid |
| bm25s [48] | BM25 | 0.3.11 | 2026-08-25 | MIT | default |
| rank-bm25 [49] | BM25 | 0.2.2 | 2022-02-16 | Apache-2.0 | stale; prefer bm25s |
| hdbscan [50] / scikit-learn [51] | batch clustering | 0.8.44 / 1.9.1 | 2026-06 / 2026-09 | BSD-3-Clause | nightly pass |
| bertopic [53] | topic modelling | 0.17.4 | 2025-12-03 | MIT | digest themes |
| river [55] | online clustering | 0.26.1 | 2026-08-21 | BSD-3-Clause | optional |

## REFERENCES

[1] Scrapy project. w3lib API documentation (canonicalize_url, url_query_cleaner). 2026. [w3lib docs](https://w3lib.readthedocs.io/en/latest/w3lib.html)
[2] PyPI. w3lib. 2026. [pypi.org/project/w3lib](https://pypi.org/project/w3lib/)
[3] niksite. url-normalize (GitHub README). 2026. [github.com/niksite/url-normalize](https://github.com/niksite/url-normalize)
[4] PyPI. url-normalize. 2026. [pypi.org/project/url-normalize](https://pypi.org/project/url-normalize/)
[5] Barbaresi A. courlan: clean, filter and sample URLs (GitHub README). 2026. [github.com/adbar/courlan](https://github.com/adbar/courlan)
[6] PyPI. courlan. 2026. [pypi.org/project/courlan](https://pypi.org/project/courlan/)
[7] PyPI. trafilatura. 2026. [pypi.org/project/trafilatura](https://pypi.org/project/trafilatura/)
[8] ClearURLs. Rules database for the ClearURLs extension. 2026. [github.com/ClearURLs/Rules](https://github.com/ClearURLs/Rules)
[9] Google Search Central. How to specify a canonical URL with rel="canonical" and other methods. 2026. [developers.google.com](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
[10] arXiv. Understanding the arXiv identifier. 2026. [info.arxiv.org](https://info.arxiv.org/help/arxiv_identifier.html)
[11] GitHub Docs. Renaming a repository. 2026. [docs.github.com](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)
[12] PyPI. xxhash. 2026. [pypi.org/project/xxhash](https://pypi.org/project/xxhash/)
[13] RSS Advisory Board. RSS 2.0 Specification (guid element). 2009. [rssboard.org](https://www.rssboard.org/rss-specification)
[14] Manku GS, Jain A, Das Sarma A. Detecting near-duplicates for web crawling. WWW 2007. [research.google/pubs/pub33026](https://research.google/pubs/pub33026/)
[15] PyPI. simhash. 2022. [pypi.org/project/simhash](https://pypi.org/project/simhash/)
[16] PyPI. simhash-py. 2017. [pypi.org/project/simhash-py](https://pypi.org/project/simhash-py/)
[17] Zhu E. datasketch documentation: MinHash LSH. 2026. [ekzhu.com/datasketch/lsh.html](https://ekzhu.com/datasketch/lsh.html)
[18] PyPI. datasketch. 2026. [pypi.org/project/datasketch](https://pypi.org/project/datasketch/)
[19] Mou C. text-dedup (GitHub README). 2026. [github.com/ChenghaoMou/text-dedup](https://github.com/ChenghaoMou/text-dedup)
[20] MinishLab. model2vec (GitHub README). 2026. [github.com/MinishLab/model2vec](https://github.com/MinishLab/model2vec)
[21] PyPI. model2vec. 2026. [pypi.org/project/model2vec](https://pypi.org/project/model2vec/)
[22] MinishLab. semhash (GitHub README). 2026. [github.com/MinishLab/semhash](https://github.com/MinishLab/semhash)
[23] PyPI. semhash. 2026. [pypi.org/project/semhash](https://pypi.org/project/semhash/)
[24] Qdrant. fastembed (GitHub README). 2026. [github.com/qdrant/fastembed](https://github.com/qdrant/fastembed)
[25] PyPI. fastembed. 2026. [pypi.org/project/fastembed](https://pypi.org/project/fastembed/)
[26] PyPI. sentence-transformers. 2026. [pypi.org/project/sentence-transformers](https://pypi.org/project/sentence-transformers/)
[27] sentence-transformers. all-MiniLM-L6-v2 model card. 2026. [huggingface.co](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
[28] BAAI. bge-small-en-v1.5 model card. 2026. [huggingface.co](https://huggingface.co/BAAI/bge-small-en-v1.5)
[29] PyPI. usearch. 2026. [pypi.org/project/usearch](https://pypi.org/project/usearch/)
[30] PyPI. faiss-cpu. 2026. [pypi.org/project/faiss-cpu](https://pypi.org/project/faiss-cpu/)
[31] pyahocorasick. Documentation. 2026. [pyahocorasick.readthedocs.io](https://pyahocorasick.readthedocs.io/en/latest/)
[32] PyPI. pyahocorasick. 2026. [pypi.org/project/pyahocorasick](https://pypi.org/project/pyahocorasick/)
[33] PyPI. flashtext. 2018. [pypi.org/project/flashtext](https://pypi.org/project/flashtext/)
[34] Explosion. spaCy API: EntityRuler. 2026. [spacy.io/api/entityruler](https://spacy.io/api/entityruler)
[35] PyPI. spacy. 2026. [pypi.org/project/spacy](https://pypi.org/project/spacy/)
[36] RapidFuzz. process module documentation. 2026. [rapidfuzz.github.io](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html)
[37] PyPI. rapidfuzz. 2026. [pypi.org/project/rapidfuzz](https://pypi.org/project/rapidfuzz/)
[38] PyPI. jellyfish. 2025. [pypi.org/project/jellyfish](https://pypi.org/project/jellyfish/)
[39] UK Ministry of Justice. Splink documentation. 2026. [moj-analytical-services.github.io/splink](https://moj-analytical-services.github.io/splink/index.html)
[40] PyPI. splink. 2026. [pypi.org/project/splink](https://pypi.org/project/splink/)
[41] DataMade. dedupe (GitHub README). 2025. [github.com/dedupeio/dedupe](https://github.com/dedupeio/dedupe)
[42] PyPI. dedupe. 2024. [pypi.org/project/dedupe](https://pypi.org/project/dedupe/)
[43] PyPI. recordlinkage. 2023. [pypi.org/project/recordlinkage](https://pypi.org/project/recordlinkage/)
[44] Peeters R, Steiner A, Bizer C. Entity Matching using Large Language Models. arXiv:2310.11244. 2023. [arxiv.org/abs/2310.11244](https://arxiv.org/abs/2310.11244)
[45] Allan J, Carbonell J, Doddington G, Yamron J, Yang Y. Topic Detection and Tracking Pilot Study: Final Report. DARPA Broadcast News Workshop 1998. [semanticscholar.org](https://www.semanticscholar.org/paper/Topic-Detection-and-Tracking-Pilot-Study-Final-Allan-Carbonell/a0a3ac06d4e4b0ef1cd2354417f4f83bc0997131)
[46] Petrović S, Osborne M, Lavrenko V. Streaming First Story Detection with application to Twitter. NAACL-HLT 2010. [aclanthology.org/N10-1021](https://aclanthology.org/N10-1021/)
[47] Lù XH. bm25s (GitHub README). 2026. [github.com/xhluca/bm25s](https://github.com/xhluca/bm25s)
[48] PyPI. bm25s. 2026. [pypi.org/project/bm25s](https://pypi.org/project/bm25s/)
[49] PyPI. rank-bm25. 2022. [pypi.org/project/rank-bm25](https://pypi.org/project/rank-bm25/)
[50] PyPI. hdbscan. 2026. [pypi.org/project/hdbscan](https://pypi.org/project/hdbscan/)
[51] scikit-learn. sklearn.cluster.HDBSCAN. 2026. [scikit-learn.org](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)
[52] hdbscan. Predicting clusters for new points. 2026. [hdbscan.readthedocs.io](https://hdbscan.readthedocs.io/en/latest/prediction_tutorial.html)
[53] PyPI. bertopic. 2025. [pypi.org/project/bertopic](https://pypi.org/project/bertopic/)
[54] Grootendorst M. BERTopic: Online Topic Modeling. 2026. [maartengr.github.io/BERTopic](https://maartengr.github.io/BERTopic/getting_started/online/online.html)
[55] river. DBSTREAM API reference. 2026. [riverml.xyz](https://riverml.xyz/latest/api/cluster/DBSTREAM/)
