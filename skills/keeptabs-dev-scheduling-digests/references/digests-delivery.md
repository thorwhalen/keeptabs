# Digests and delivery: generating "what's new" digests and publishing them

Research note for the veille (technology watch) package. Scope: (A) how to turn a window of newly acquired, matched and deduplicated items into a trustworthy digest, with or without an LLM; (B) how to deliver that digest by email, Slack, GitHub Discussions, static pages/feeds and chat webhooks, behind one `publish(digest, *, channel)` seam. Facts were checked on 2026-09-27; prices and free tiers change, so every number below carries a reference.

## 1. Summary

- **Build the digest as data first, prose second.** The digest is a list of structured items (`title`, `one_line`, `why_it_matters`, `entity`, `source_ids`) grouped into sections. Rendering to Markdown, HTML email, Slack blocks, a GitHub discussion body or an Atom feed is a pure function of that data, so every channel gets the same content and the no-LLM fallback is the same pipeline minus the model.
- **The LLM never writes a URL.** It may only cite opaque item IDs taken from the input; code resolves IDs to URLs. With Anthropic structured outputs the allowed IDs can be an `enum` in the JSON schema, which constrained decoding enforces [2]. This removes the whole class of hallucinated links, which recent measurements still put in the percent range even for strong models and agents [4].
- **Cheap model per item, stronger model once per digest**, batched and cached: the Batch API halves token prices and stacks with prompt caching [8][9].
- **Zero-key default delivery:** write the digest to local Markdown/HTML plus an Atom and JSON Feed, and optionally post a GitHub discussion through the already-authenticated `gh` CLI. Keyed options (SMTP app password, Slack webhook, Resend, Buttondown) are adapters behind the same protocol.

## 2. Part A: generating digests

### 2.1 Pipeline shape

A digest run has a **window** (items first seen since the last successful digest for that audience, not "last 7 days", so a failed run does not drop items) and a **ledger** of what previous digests already covered (item IDs and entity IDs), so an item that re-surfaces through a second source is folded into the earlier story instead of reported twice.

Recommended stages:

1. **Select**: items in the window, already matched to tracked entities and deduplicated upstream; drop items whose canonical ID appears in the previous-digest ledger unless they carry a material update (new version, new benchmark number).
2. **Cluster**: group items about the same event (same entity plus high embedding or title similarity, or shared canonical URL). Cluster-then-summarise gives one story per event with several sources, which is both shorter and better grounded than one bullet per item.
3. **Map** (cheap model, per cluster): produce one structured item per cluster. This is embarrassingly parallel and a good fit for the Batch API [8].
4. **Reduce** (stronger model, once): pick "top stories", write section intros and the "signals" section from the mapped items only, never from raw documents. This is the hierarchical-merging pattern; the BooookScore study found hierarchical merging gives more coherent summaries than incremental updating, at some cost in detail [1], which is the right tradeoff for a digest whose detail lives behind the links.
5. **Verify** (code, then optionally a checker model): resolve IDs, drop invalid ones, check links, optionally score faithfulness.
6. **Render** per channel.

If the window is small (tens of items), skip clustering and map: a single call with all item abstracts fits comfortably in current context windows. Map-reduce matters when the window holds hundreds of items or full texts.

### 2.2 Digest structure

Best-practice sections, all derived from the structured items:

- **Top stories** (3 to 5): highest score across all topics, one line each, links first.
- **Per tracked topic**: one section per spec file / subject area, ordered by the user's priority.
- **New entities**: things that were not in the tracked-entity store before this window (a new model, library, company, paper series). This is often the most valuable section for a veille and is computed, not generated.
- **Updates to tracked entities**: releases, version bumps, benchmark changes, funding, deprecations.
- **Signals / weak signals**: low-volume but novel mentions (a term appearing for the first time across several unrelated sources). Label these explicitly as speculative.
- **Since last digest** header: the window bounds and counts ("142 items, 37 stories, 5 new entities").
- **Links first**: each item leads with the linked title so a reader can act without reading prose; `why_it_matters` is one sentence, optional.

### 2.3 Structured output per item

A per-item schema (Pydantic or a dataclass exported to JSON Schema):

```python
from dataclasses import dataclass, field


@dataclass
class DigestItem:
    title: str
    one_line: str
    why_it_matters: str
    entity: str  # tracked entity key, or "new:<slug>"
    source_ids: list[str]  # item IDs from the input window, never URLs
    kind: str = "update"  # "update" | "new_entity" | "signal"


@dataclass
class Digest:
    window: tuple[str, str]  # ISO timestamps
    sections: dict[str, list[DigestItem]] = field(default_factory=dict)
    top: list[DigestItem] = field(default_factory=list)
```

Anthropic structured outputs (`output_config.format` with `type: json_schema`) guarantee schema-valid JSON through constrained decoding, and support `enum`, `$ref` and `additionalProperties: false`; they do not support recursive schemas or string/number length constraints [2]. OpenAI-style and other providers have equivalents; the provider-agnostic libraries in section 2.7 paper over the differences.

### 2.4 The "ID-only citations" pattern

The model sees items as `[{"id": "k7f2", "title": ..., "abstract": ...}]` with no URLs at all. It must cite `source_ids`. Code maps IDs back to canonical URLs. Two layers of enforcement:

- **Schema layer**: build the schema per call so `source_ids.items` is an `enum` of the input IDs. Constrained decoding then cannot emit any other ID [2]. Very large enums may hit schema-size or grammar limits, so keep IDs short and cluster first.
- **Code layer**: always re-validate (other providers may not constrain), drop unknown IDs, and drop an item whose `source_ids` becomes empty.

```python
import json


def id_only_schema(item_ids: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title",
                        "one_line",
                        "why_it_matters",
                        "entity",
                        "source_ids",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "one_line": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "entity": {"type": "string"},
                        "source_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "enum": item_ids},
                        },
                    },
                },
            }
        },
    }


def summarize_window(items: dict, *, complete) -> list[dict]:
    """items: {id: {"title", "abstract", "url", ...}}; complete: (prompt, schema) -> dict."""
    payload = [
        {"id": k, "title": v["title"], "abstract": v.get("abstract", "")}
        for k, v in items.items()
    ]  # no URLs reach the model
    prompt = (
        "Summarise these items for a technology-watch digest. "
        "Cite only by `id`. Do not invent facts not present in the items.\n"
        + json.dumps(payload)
    )
    out = complete(prompt, id_only_schema(list(items)))["items"]
    resolved = []
    for it in out:
        ids = [i for i in it["source_ids"] if i in items]  # re-validate
        if ids:
            resolved.append({**it, "sources": [items[i]["url"] for i in ids]})
    return resolved
```

`complete` is the LLM seam (section 2.7); passing it in keeps the pattern provider-agnostic and testable with a stub.

**Anthropic Citations API** is the complementary tool for free-prose sections (section intros, the weak-signals paragraph). Items are passed as `document` blocks (plain text, PDF or "custom content" documents whose blocks are not re-chunked), and the response interleaves text with citation objects that point to document and block indices; the docs state these are "guaranteed to contain valid pointers to the provided documents", and `cited_text` is not billed as output tokens [3]. Put one item per custom-content block and the returned block index is the item ID. Caveat: Citations and structured outputs cannot be combined in one request (the API returns 400) [3], so use structured outputs for the item list and Citations for prose.

### 2.5 Avoiding hallucinated links and facts

- No URLs in the prompt and no free-text URL fields in the schema; links are rendered only from the item store.
- **Link verification** in code before publishing: HEAD (fall back to GET) each resolved URL with a short timeout, record status in the item store, and mark or drop dead links. This also catches upstream feed rot. Studies of LLM and deep-research citations find a non-trivial share of supplied URLs never existed (roughly 3 to 13 percent with no Wayback record in one 2026 measurement) [4][5], so this check stays worthwhile even with ID-only citations for any path where a model can still reach a URL (for example agent-written answers).
- **Numbers and names**: instruct the map step to copy version numbers, benchmark scores and names verbatim from the item; in code, flag any digit sequence in `one_line` that does not occur in the cited items' text. This cheap lexical check catches most numeric hallucinations.
- **Faithfulness scoring (optional)**: a claim-level checker such as MiniCheck, a 770M-parameter model reported to reach GPT-4-level grounding accuracy at about 400x lower cost [6], can score each `one_line` against its cited items' text and demote low-scoring items to "unverified". An LLM-as-judge with the strong model is the zero-extra-dependency alternative.
- **Weak signals** are labelled as such in rendering, so speculative synthesis is never presented as fact.

### 2.6 Cost control

- **Model split**: a small model for map, a stronger one for reduce. Current Anthropic list prices: Haiku 4.5 at $1 / $5 per million input/output tokens, Sonnet 5 at $2 / $10, Opus 5.5 at $4 / $20 [9].
- **Batch API**: 50 percent off input and output, most batches finish within an hour [8][9]. A scheduled veille run tolerates that latency, so map calls should default to batch.
- **Prompt caching**: the static instructions and the tracked-entity glossary are the shared prefix; cache reads cost 0.1x base input (0.05x on Opus 5.5), writes 1.25x (5 min) or 2x (1 h), and caching stacks with the Batch discount [7][9].
- **Order-of-magnitude**: 300 items at about 400 input tokens and 120 output tokens each through batched Haiku is about 120k input and 36k output tokens, i.e. roughly $0.06 + $0.09 = $0.15 per run before caching; one Sonnet reduce call over the mapped items adds a few cents. Cost is dominated by acquisition-side full-text reading, not digest generation.
- **Skip the LLM when there is nothing to say**: if the window is empty or under a threshold, emit the no-LLM digest (or nothing).

### 2.7 Provider-agnostic LLM clients

| Library | Latest (checked) | License | Structured output | Notes |
|---|---|---|---|---|
| `llm` (Simon Willison) | 0.36, 2026-09-22 [13] | Apache-2.0 | JSON schemas, concise schema syntax [13] | CLI + Python, plugin per provider (incl. local via Ollama plugin), logs to SQLite. Lightest good default. |
| `litellm` | 1.102.1, 2026-09-23 [10] | MIT | via OpenAI-format `response_format` | 100+ providers, proxy/gateway [10]. Malicious 1.82.7/1.82.8 were published to PyPI on 2026-03-24 after a credential compromise [11][12]: if used, pin exact versions with hashes. Heavy dependency tree. |
| `aisuite` | active repo, 16.3k stars [14] | MIT | tool calling; thin chat API | `provider:model` strings; latest release date not confirmed, treat as lower-cadence. |
| `pydantic-ai` | 2.51.0, 2026-09-25 [15] | MIT | typed outputs via Pydantic | Full agent framework; more than a digest needs, attractive if the package already uses Pydantic agents. |
| `instructor` | 1.17.0, 2026-09-09 [16] | MIT | Pydantic models with validation retries [16] | Good when validators should reject and retry (e.g. unknown `source_ids`). |
| `anthropic` SDK | n/a | MIT | native `output_config.format`, Citations, Batches, caching [2][3][8] | Needed to use Citations and Batches fully; wrap behind the same seam. |

Recommendation for the seam: `complete(prompt, schema, *, model=None) -> dict`, default implementation on `llm` (small, Apache-2.0, schemas, local models possible, user-configurable keys already managed by `llm keys`), optional adapter on the native Anthropic SDK for Citations and Batches. Avoid making `litellm` a hard dependency.

### 2.8 No-LLM fallback digest

Always available and the default when no model is configured: group items by section (topic, then entity), sort by score and recency, render `title` as the link text, source domain, date and the first sentence of the item's own abstract (extractive, so it cannot hallucinate). "New entities" and "updates" sections are computed from the entity store and work identically. The LLM path should produce the same `Digest` object so renderers and publishers do not know which path ran.

## 3. Part B: delivery channels

### 3.1 Email

**SMTP with the standard library** (`smtplib` + `email.message.EmailMessage`) is zero-dependency. For a personal Gmail account, Google requires 2-Step Verification and a 16-character app password for SMTP clients [17]. Sending a digest to yourself from your own authenticated mailbox is the most deliverable option available: it is signed by the provider and lands in the inbox, with no domain setup. Limits are ample for a digest: the Gmail API documents 100 quota units per `messages.send` and 6,000 units per user per minute [18]; Google Workspace documents per-user daily sending limits [19], and third-party summaries put consumer Gmail at about 500 per day [20].

```python
import smtplib
from email.message import EmailMessage


def send_email(
    subject, html, text, *, to, sender, host="smtp.gmail.com", port=465, password
):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(
            sender, password
        )  # app password from env/keyring, never in config files
        s.send_message(msg)
```

**Gmail API send** avoids storing an app password (OAuth token instead) but adds Google client libraries and an OAuth consent setup; worth it only if the package already reads Gmail (e.g. for newsletter ingestion).

**Transactional services** (all need a verified sending domain and an API key):

| Service | Free tier (2026) | Paid entry | Notes |
|---|---|---|---|
| Resend | 3,000/month, 100/day, 1 domain, permanent [21] | $20/month for 50k [22] | Simple REST API, good DX |
| Postmark | 100/month developer plan, never expires [23] | $15/month for 10k [23] | Strong deliverability reputation |
| Mailgun | 100/day, 1 domain [24] | $15/month for 10k [24] | 1-day log retention on free |
| Amazon SES | 3,000/month for 12 months for new accounts (reported) [26] | $0.10 per 1,000 a la carte; new Essentials/Pro/Enterprise plans since 2026-07-21 [25] | Cheapest at scale, AWS setup overhead |
| SendGrid | No free plan: retired 2025-05-27; new accounts get a 60-day trial at 100/day [27][28] | about $19.95/month [29] | Not recommended for a free default |

**HTML email rendering**: Jinja2 templates render the `Digest`; CSS must then be inlined for mail clients. `css-inline` (Rust core, MIT, 0.21.3 released 2026-09-14) reports about 20x the speed of premailer [30]; `premailer` (BSD-3, lxml + cssutils) still works but its declared Python support stops at 3.8 in the repo's tox config [31]. For responsive layout without Node, the `mjml` PyPI package is a pure-Python MJML implementation (MIT, 0.12.0, 2025-12-27) [32]. For a single-column link list, a hand-written table layout plus `css-inline` is enough; MJML is optional.

**Newsletter platforms** (when the digest has subscribers, which also moves unsubscribe handling and compliance off the package): Buttondown has an API-first design available on every plan, including a free plan up to 100 subscribers, then $9/month to 1,000 [33][34]. `POST /emails` takes `subject` and a Markdown `body`, with `status` values such as `draft`, `about_to_send`, `scheduled`; bodies beginning with YAML front matter are rejected unless an override header is set [35]. Publishing as `draft` first gives a human-review gate for free.

### 3.2 Slack

Two options:

- **Incoming webhook**: one URL per channel, fixed at install; cannot override channel, username or icon; cannot delete messages afterwards [36]. Zero dependencies (plain HTTPS POST). Right choice for "post the weekly digest to #veille".
- **Bot token + `chat.postMessage`** (`chat:write` scope): any channel the bot is in, threads, updates and deletes [37]. `slack_sdk` 3.44.1 (MIT, 2026-09-03) is the official client [38].

Limits that shape rendering: 50 blocks per message (100 in modals) [39]; a section block's `text` is at most 3,000 characters, with up to 10 `fields` of 2,000 each [40]; top-level `text` is recommended under 4,000 characters and truncated beyond 40,000 [37]; posting is about 1 message per second per channel, with short bursts tolerated, for webhooks and `chat.postMessage` alike [41]. So: one header message with top stories, then one message (or thread reply) per section, splitting on the 50-block and 3,000-char limits.

```python
import json, urllib.request


def _blocks(digest, *, max_chars=3000):
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": digest["title"][:150]},
        }
    ]
    for section, items in digest["sections"].items():
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{section}*"}}
        )
        lines = [
            f"• <{it['sources'][0]}|{it['title']}> — {it['one_line']}" for it in items
        ]
        chunk = ""
        for line in lines:  # respect the 3,000-char section limit
            if len(chunk) + len(line) + 1 > max_chars:
                blocks.append(
                    {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
                )
                chunk = ""
            chunk += line + "\n"
        if chunk:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
            )
    return blocks


def post_slack_webhook(digest, *, webhook_url, max_blocks=50):
    blocks = _blocks(digest)
    for i in range(0, len(blocks), max_blocks):  # respect the 50-block message limit
        body = {"text": digest["title"], "blocks": blocks[i : i + max_blocks]}
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
```

(Slack mrkdwn needs `&`, `<` and `>` escaped in titles; omitted here for brevity.)

### 3.3 GitHub Discussions

Creating a discussion is GraphQL-only: the `createDiscussion` mutation takes `repositoryId`, `categoryId`, `title` and `body` (Markdown), and GitHub's guide documents only GraphQL for discussions; classic tokens need `public_repo` (public repositories) or `repo` (private) [42]. Community threads confirm there is no REST endpoint for discussions [43][44]. The `gh` CLI can call GraphQL directly [45], which makes this a zero-new-key channel for anyone with `gh auth login` done. Inside GitHub Actions, the workflow token needs the discussions write permission (set it in the workflow's `permissions` block; verify at setup).

```bash
# 1) look up IDs once and store them in the channel config
gh api graphql -f query='
  query($owner:String!, $name:String!) {
    repository(owner:$owner, name:$name) {
      id
      discussionCategories(first: 20) { nodes { id name } }
    }
  }' -f owner=OWNER -f name=REPO

# 2) create the discussion (body read from the rendered Markdown file)
gh api graphql -f query='
  mutation($repo:ID!, $cat:ID!, $title:String!, $body:String!) {
    createDiscussion(input:{repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) {
      discussion { url }
    }
  }' -f repo="$REPO_ID" -f cat="$CATEGORY_ID" \
     -f title="Veille digest 2026-09-27" -F body=@digest.md --jq .data.createDiscussion.discussion.url
```

A dedicated "Digests" category (announcement-type, so only maintainers post) keeps the stream tidy; readers can then comment on individual digests, which gives a free feedback channel for the agent.

### 3.4 Static pages and feeds

The most robust zero-key channel: write `digests/2026-09-27.md` / `.html`, plus an index, plus feeds. Any static host (GitHub Pages included) can serve the directory, and feed readers become the subscription mechanism.

- **Atom/RSS via `feedgen`**: 1.0.0 (2023-12-25), dual BSD-2-Clause / LGPL-3.0+, depends on lxml [46][47]. Mature but slow-moving; the repository is still maintained with a small open-issue count [47]. If lxml is unwanted, Atom is small enough to emit from a Jinja2 template.
- **JSON Feed 1.1**: required top-level `version` (`https://jsonfeed.org/version/1.1`), `title`, `items`; each item needs `id` plus `content_html` or `content_text`; serve as `application/feed+json` [48]. Trivial to emit with `json.dumps`, zero dependencies.

```python
from feedgen.feed import FeedGenerator


def write_atom(digests, *, out_path, site_url, title="Veille digests"):
    fg = FeedGenerator()
    fg.id(site_url)
    fg.title(title)
    fg.link(href=site_url, rel="alternate")
    for d in digests:  # newest last; feedgen prepends
        fe = fg.add_entry()
        fe.id(f"{site_url}/digests/{d['slug']}")
        fe.title(d["title"])
        fe.link(href=f"{site_url}/digests/{d['slug']}.html")
        fe.updated(d["published"])  # timezone-aware datetime
        fe.content(d["html"], type="html")
    fg.atom_file(out_path)
```

A per-topic feed (one feed per spec file) is a cheap, high-value extra: subscribers pick only the areas they care about.

### 3.5 Discord, Telegram, and multi-channel via Apprise

- **Discord webhooks**: 2,000 characters of `content`, up to 10 embeds totalling 6,000 characters, embed description up to 4,096 [49]. Post top stories only, with a link to the full digest page.
- **Telegram Bot API**: `sendMessage` text is limited to 4,096 characters [50]; same "headline plus link" strategy.
- **Apprise**: one URL syntax for 100+ services (Slack, Discord, Telegram, email, ntfy, and more), BSD-2-Clause, Python 3.9+, version 2.0.0 released 2026-09-26, about 17k stars [51][52]. It is ideal as a catch-all "notify me that a digest is out" adapter, but it sends title plus body (Markdown where the service supports it), not Slack Block Kit or GitHub discussions, so it complements rather than replaces the rich channels.

## 4. Seam design: `publish(digest, *, channel)`

```python
from typing import Protocol, Mapping, Callable


class Publisher(Protocol):
    def __call__(
        self, digest: "Digest", /, **options
    ) -> str: ...  # returns a receipt (URL, message id, path)


PUBLISHERS: Mapping[str, Publisher] = {
    "files": publish_files,  # md + html + atom + json feed to a directory (default, no key)
    "github": publish_github,  # gh api graphql createDiscussion
    "email": publish_smtp,  # smtplib; transactional services as alternative strategies
    "slack": publish_slack,  # webhook by default, bot token if provided
    "apprise": publish_apprise,  # anything else, as a notification
}


def publish(
    digest, *, channel: str | Publisher = "files", dry_run: bool = False, **options
) -> str:
    fn = PUBLISHERS[channel] if isinstance(channel, str) else channel
    if dry_run:
        return render_preview(
            digest, channel=channel
        )  # what would be sent, sent nowhere
    return fn(digest, **options)
```

Design points:

- **Renderers are separate from publishers**: `render_markdown`, `render_email_html`, `render_slack_blocks`, `render_atom` take a `Digest`; publishers only transport. A new channel is one renderer plus one transport, and the core never changes.
- **Channels are declared in config** (a `channels:` list in the watch spec: `{kind: slack, webhook_env: VEILLE_SLACK_URL}`), secrets referenced by environment variable or keyring name only, never stored in spec files.
- **Idempotency**: record `(digest_id, channel) -> receipt` in the key-value store before returning; a retried run skips channels that already succeeded. This matters for email and discussions, which cannot be un-sent.
- **Dry run and draft modes** (render to a local file; Buttondown `status=draft`) give an agent-friendly review gate before anything goes out.
- **The previous-digest ledger** (section 2.1) is written only after at least one channel succeeds, so the next window starts at the right place.

## 5. Comparison of delivery options

| Channel | Key needed | Extra dependency | Free limits | Rich formatting | Two-way | Best for |
|---|---|---|---|---|---|---|
| Local files + Atom/JSON Feed | none | none (feedgen optional) | unlimited | full HTML | no | default archive, feed readers, Pages |
| GitHub Discussions via `gh` | existing `gh` auth | none (`gh` CLI) | GitHub API limits | Markdown | yes (comments) | team/open-source audiences |
| SMTP (Gmail app password) | app password | none | about 500/day consumer [20] | HTML | replies | personal digest to self |
| Slack incoming webhook | webhook URL | none | about 1 msg/s/channel [41] | Block Kit, 50 blocks [39] | no | a team channel |
| Slack bot (`slack_sdk`) | bot token | slack_sdk | same | Block Kit, threads | yes | threaded per-section digests |
| Resend / Postmark / Mailgun | API key + domain | requests or SDK | 3,000/mo; 100/mo; 100/day [21][23][24] | HTML | no | branded email to others |
| Amazon SES | AWS creds + domain | boto3 | 3,000/mo first year (reported) [26] | HTML | no | volume at lowest unit cost |
| Buttondown | API key | none (REST) | 100 subscribers [33] | Markdown to HTML | subscribers | public newsletter with unsubscribe handled |
| Apprise | per-service URL | apprise | per service | title + body | no | "digest is out" pings anywhere |
| Discord / Telegram | webhook / bot token | none | 2,000 / 4,096 chars [49][50] | limited | no | headline + link |

## 6. Recommendation

**Zero-key default (ships in v1, no API key, no new heavy dependency):**

- Generation: the no-LLM grouped digest (extractive, computed sections for new entities and updates), producing the same `Digest` data object the LLM path produces.
- Delivery: `channel="files"` writes Markdown, HTML, an Atom feed and a JSON Feed per run into the package's data directory (servable by GitHub Pages or any static host), and `channel="github"` posts a discussion through the user's existing `gh` authentication with the `createDiscussion` mutation.
- Email to self through stdlib `smtplib` is the first keyed step (an app password, not an API key), because it is the most deliverable path for a personal digest.

**Stronger optional path:**

- Generation: LLM seam `complete(prompt, schema)` defaulting to Simon Willison's `llm` (Apache-2.0, schema support, local or hosted models), with a native Anthropic adapter when the user wants Batches (50 percent off), prompt caching and the Citations API for prose sections. Always use the ID-only citation pattern with the ID `enum` in the schema, re-validate in code, verify links, and optionally score faithfulness with MiniCheck.
- Delivery: Slack incoming webhook for team channels (upgrade to `slack_sdk` bot for threads), Resend (permanent 3,000/month free tier) when email must go to other people from a domain, Buttondown when the digest has real subscribers, and Apprise as the catch-all notification adapter. Avoid SendGrid as a default (no free plan since 2025) and avoid a hard dependency on `litellm` (heavy, and it had a PyPI compromise in March 2026).

## REFERENCES

[1] Chang Y, Lo K, Goyal T, Iyyer M. BooookScore: A systematic exploration of book-length summarization in the era of LLMs. 2023. [arXiv:2310.00785](https://arxiv.org/abs/2310.00785)
[2] Anthropic. Structured outputs. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
[3] Anthropic. Citations. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/citations)
[4] Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents. 2026. [arXiv:2604.03173](https://arxiv.org/html/2604.03173v1)
[5] Runzbuzz. When AI Makes Up Links: Measuring URL Hallucinations in ChatGPT and Gemini. 2026. [blog.runzbuzz.com](https://blog.runzbuzz.com/posts/ai-search-url-hallucination)
[6] Tang L, Laban P, Durrett G. MiniCheck: Efficient Fact-Checking of LLMs on Grounding Documents. EMNLP 2024. [arXiv:2404.10774](https://arxiv.org/abs/2404.10774)
[7] Anthropic. Prompt caching. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
[8] Anthropic. Batch processing. 2026. [platform.claude.com](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
[9] Anthropic. Pricing. 2026. [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing)
[10] BerriAI. litellm on PyPI. 2026. [pypi.org/project/litellm](https://pypi.org/project/litellm/)
[11] LiteLLM. Security Update: Suspected Supply Chain Incident. 2026. [docs.litellm.ai](https://docs.litellm.ai/blog/security-update-march-2026)
[12] Datadog Security Labs. LiteLLM and Telnyx compromised on PyPI: Tracing the TeamPCP supply chain campaign. 2026. [securitylabs.datadoghq.com](https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-teampcp-supply-chain-campaign/)
[13] Willison S. llm on PyPI. 2026. [pypi.org/project/llm](https://pypi.org/project/llm/)
[14] Ng A et al. aisuite. 2026. [github.com/andrewyng/aisuite](https://github.com/andrewyng/aisuite)
[15] Pydantic. pydantic-ai on PyPI. 2026. [pypi.org/project/pydantic-ai](https://pypi.org/project/pydantic-ai/)
[16] instructor on PyPI. 2026. [pypi.org/project/instructor](https://pypi.org/project/instructor/)
[17] Google. Sign in with app passwords. Gmail Help. 2026. [support.google.com](https://support.google.com/mail/answer/185833?hl=en)
[18] Google. Usage limits, Gmail API. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/api/reference/quota)
[19] Google. Gmail sending limits in Google Workspace. 2026. [support.google.com](https://support.google.com/a/answer/166852?hl=en)
[20] Unipile. Gmail API Limits in 2026: Quotas, Rate Limits, and How to Handle Them. 2026. [unipile.com](https://www.unipile.com/gmail-api-limits/)
[21] Resend. What are Resend account quotas and limits? 2026. [resend.com](https://resend.com/docs/knowledge-base/account-quotas-and-limits)
[22] Flexprice. Resend Pricing in 2026: Every Plan, Price, and Overage Rate Explained. 2026. [flexprice.io](https://flexprice.io/blog/detailed-resend-pricing-guide)
[23] Postmark. Pricing. 2026. [postmarkapp.com](https://postmarkapp.com/pricing)
[24] Mailgun. What does the Free plan offer? 2026. [help.mailgun.com](https://help.mailgun.com/hc/en-us/articles/203068914-What-does-the-Free-plan-offer)
[25] AWS. Amazon SES introduces pricing plans. 2026. [aws.amazon.com](https://aws.amazon.com/about-aws/whats-new/2026/07/amazon-ses-pricing-plans/)
[26] SaaS Price Pulse. Amazon SES Pricing 2026: Free Tier Catches to Know. 2026. [saaspricepulse.com](https://www.saaspricepulse.com/tools/amazon-ses)
[27] Twilio. Changes coming to SendGrid's Free Plan. 2025. [twilio.com](https://www.twilio.com/en-us/changelog/sendgrid-free-plan)
[28] Twilio SendGrid. Overview of 60-Day Free Trial Plans for New SendGrid Accounts. 2025. [support.sendgrid.com](https://support.sendgrid.com/hc/en-us/articles/35270136965403-Twilio-SendGrid-Trial-Account-Plan)
[29] Mystrika. SendGrid Free Tier: What Happened and the Best Alternatives in 2026. 2026. [blog.mystrika.com](https://blog.mystrika.com/sendgrid-free-tier/)
[30] Stranger6667. css-inline on PyPI. 2026. [pypi.org/project/css-inline](https://pypi.org/project/css-inline/)
[31] Bengtsson P. premailer. [github.com/peterbe/premailer](https://github.com/peterbe/premailer)
[32] mjml (pure-Python) on PyPI. 2025. [pypi.org/project/mjml](https://pypi.org/project/mjml/)
[33] Sequenzy. Buttondown Pricing Explained (2026). 2026. [sequenzy.com](https://www.sequenzy.com/pricing/buttondown)
[34] Buttondown. Email Newsletter API Integration for Developers. 2026. [buttondown.com](https://buttondown.com/features/api)
[35] Buttondown. Creating an email (API). 2026. [docs.buttondown.com](https://docs.buttondown.com/api-emails-create)
[36] Slack. Sending messages using incoming webhooks. 2026. [docs.slack.dev](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks)
[37] Slack. chat.postMessage method. 2026. [docs.slack.dev](https://docs.slack.dev/reference/methods/chat.postMessage)
[38] Slack. slack-sdk on PyPI. 2026. [pypi.org/project/slack-sdk](https://pypi.org/project/slack-sdk/)
[39] Slack. Blocks reference. 2026. [docs.slack.dev](https://docs.slack.dev/reference/block-kit/blocks)
[40] Slack. Section block. 2026. [docs.slack.dev](https://docs.slack.dev/reference/block-kit/blocks/section-block)
[41] Slack. Rate limits. 2026. [docs.slack.dev](https://docs.slack.dev/apis/web-api/rate-limits/)
[42] GitHub. Using the GraphQL API for Discussions. 2026. [docs.github.com](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions)
[43] GitHub Community. Discussions REST API (discussion 4327). [github.com/orgs/community](https://github.com/orgs/community/discussions/4327)
[44] octokit.net. Discussions and the REST API vs GraphQL API (discussion 2774). [github.com/octokit/octokit.net](https://github.com/octokit/octokit.net/discussions/2774)
[45] GitHub Blog. Exploring GitHub CLI: How to interact with GitHub's GraphQL API endpoint. [github.blog](https://github.blog/developer-skills/github/exploring-github-cli-how-to-interact-with-githubs-graphql-api-endpoint/)
[46] Kiesow L. feedgen on PyPI. 2023. [pypi.org/project/feedgen](https://pypi.org/project/feedgen/)
[47] Kiesow L. python-feedgen. [github.com/lkiesow/python-feedgen](https://github.com/lkiesow/python-feedgen)
[48] Simmons B, Reece M. JSON Feed Version 1.1. [jsonfeed.org](https://www.jsonfeed.org/version/1.1/)
[49] discord-webhook.com. Discord Embed Limits Cheat Sheet (Characters, Fields and Total Payload). 2026. [discord-webhook.com](https://discord-webhook.com/en/blog/discord-webhook-embed-limits/)
[50] node-telegram-bot-api. sendMessage: Current maximum length is 4096 UTF8 characters (issue 165). [github.com/yagop/node-telegram-bot-api](https://github.com/yagop/node-telegram-bot-api/issues/165)
[51] Caron C. apprise on PyPI. 2026. [pypi.org/project/apprise](https://pypi.org/project/apprise/)
[52] Caron C. Apprise. [github.com/caronc/apprise](https://github.com/caronc/apprise)
