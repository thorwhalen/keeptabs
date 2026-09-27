# Ingesting email newsletters for a technology-watch package

Research date: 2026-09-27. Scope: how a scheduled, agent-driven "veille" process can read newsletters from a dedicated inbox, route them to tracked subject areas, turn each email into items and clean links, and stay on the right side of provider terms, copyright and privacy law.

## 1. Summary

- **Access.** Plain-password IMAP to Gmail is gone (all Google accounts since 2025-03-14), but **app passwords still work for IMAP** on personal accounts with 2-Step Verification, and no official retirement date for them has been announced [1][2][3][4][5]. This is the only Gmail path that needs no Google Cloud project, no OAuth client and no verification. The Gmail API is cleaner (incremental `history.list`, labels as first-class objects), but every scope that can read message bodies is *restricted*, and an OAuth client left in "Testing" issues refresh tokens that die after 7 days [7][8][10][11].
- **Default library stack** (all maintained in 2026, permissive licenses): `imap-tools` (Apache-2.0, no dependencies) for IMAP, the stdlib `email` package with `policy.default` for MIME, `selectolax` (MIT) for HTML, `markdownify` (MIT) for Markdown, and stdlib code to unwrap links. Avoid `html2text` in a permissively licensed package because it is GPL-3.0-or-later [18][19][33][35][36].
- **Routing.** Use one plus-address per *subscription* (for example `watch+simonw@example.com`), a Gmail filter on `deliveredto:` that applies a label, and identify the source by `List-Id` (RFC 2919), falling back to the sender. Matching a newsletter to *topics* should happen downstream in the matcher, not in mail routing, because most newsletters cover several topics [27][28][30].
- **Links.** First decode the destination offline (Substack, Kit/ConvertKit and Google-style redirects carry it in the URL). Follow redirects only as a bounded fallback (Mailchimp, beehiiv), and never follow unsubscribe links, because a fetch counts as a click tied to the subscriber [40][41][43][44].
- **Legal.** Publish summaries with short quotes and a link back, never full reposts. Strip subscriber-identifying tracking tokens before storing anything. Auto-confirming double opt-in emails should be off by default [31][48][59][61].

## 2. Getting at the mail

### 2.1 IMAP with an app password (the zero-key path)

Google turned off "less secure app" access in stages: new connections were blocked in summer 2024; Workspace access ended on 2024-09-30; and on 2025-03-14 IMAP, POP, SMTP, CalDAV and CardDAV stopped accepting legacy passwords for every Google Account [1][2]. The exception is **app passwords**: 16-character, per-app secrets that require 2-Step Verification. They are unavailable when 2SV uses only security keys, under Advanced Protection, and on many work or school accounts, and changing the account password revokes all of them [3][4]. A June 2026 guide confirms they still authenticate to `imap.gmail.com:993` [4]. Articles that predict an app-password "phase-out" in 2026 cite no official Google announcement [5]. Google itself calls app passwords "not recommended", so treat them as a supported but discouraged path [3].

Two properties matter for the design. First, an app password grants **full mailbox access** (read, delete, and SMTP send), which is far broader than a read-only OAuth scope. That is the main reason to use a dedicated inbox and never a personal one. Second, IMAP is not Gmail-specific. The same code works with Fastmail, a self-hosted server, or any provider that offers IMAP app passwords [50].

The OAuth route over IMAP also exists: SASL `XOAUTH2`, where the client sends `base64("user=" user "\x01auth=Bearer " token "\x01\x01")`. For Gmail it requires the `https://mail.google.com/` scope [6], which is restricted [7]. That gives you all the costs of OAuth and none of the Gmail API's benefits, so it is only worth doing for a Workspace tenant where an admin has disabled app passwords [4].

Gmail exposes its data model over IMAP through extensions. Labels appear as folders. `X-GM-LABELS` fetches and stores labels, `X-GM-RAW` runs a full Gmail web-UI search (for example `SEARCH X-GM-RAW "deliveredto:watch+simonw@example.com newer_than:2d"`), and `X-GM-MSGID` / `X-GM-THRID` are the same IDs the Gmail API uses (in decimal), so a later move to the API can keep stable keys [15].

Incremental sync over IMAP works through the pair (`UIDVALIDITY`, last seen `UID`) per folder. Store both. If `UIDVALIDITY` changes, rescan the folder. Note that the range `N:*` always returns at least the highest message, so filter `uid > last_uid` on the client.

```python
from email import message_from_bytes, policy
from imap_tools import MailBox, AND


def fetch_new(host, user, secret, *, folder, last_uid=0, uidvalidity=None):
    """Yield (uidvalidity, uid, EmailMessage) for messages newer than last_uid."""
    with MailBox(host).login(user, secret, initial_folder=folder) as mb:
        current = int(mb.folder.status(folder)["UIDVALIDITY"])
        if current != uidvalidity:
            last_uid = 0  # folder was rebuilt: full rescan
        for m in mb.fetch(AND(uid=f"{last_uid + 1}:*"), mark_seen=False, bulk=True):
            if int(m.uid) > last_uid:
                yield (
                    current,
                    int(m.uid),
                    message_from_bytes(m.obj.as_bytes(), policy=policy.default),
                )
```

### 2.2 Gmail API (the stronger, keyed path)

Scopes: `gmail.readonly`, `gmail.modify`, `gmail.metadata`, `gmail.settings.basic` (needed to create filters) and `https://mail.google.com/` are all **restricted**. Only `gmail.labels` is non-sensitive [7]. A public app that requests restricted scopes needs restricted-scope verification plus an annual third-party CASA security assessment if data touches a server, and must be re-verified every 12 months [8]. Google lists exceptions where verification is not required, including *personal use* ("only by you or a few known users"), development and testing, and internal Workspace apps [8]. Unverified apps are capped at 100 users [9].

The practical consequence for an open-source package is **bring-your-own OAuth client**. Each user creates a Google Cloud project, a Desktop OAuth client and a consent screen. This qualifies as personal use, but it is a real setup burden for a "zero-key" goal. The consent screen must also be switched from *Testing* to *In production*. An External app in Testing status gets refresh tokens that expire after **7 days**, which silently breaks any scheduled job; production status removes that limit (the user then clicks through an "unverified app" warning once) [10][11].

Sync: `users.history.list(startHistoryId=…, historyTypes=["messageAdded"], labelId=…)` returns only changes since a cursor. A historyId is "typically valid for at least a week" but sometimes only hours, and an expired one returns HTTP 404, which should trigger a full resync [12]. Costs are 2 quota units per `history.list`, 5 per `messages.list`, 20 per `messages.get` and 100 per `watch`, against 6,000 units per minute per user and 1,200,000 per minute per project [13]. That is far more than a newsletter inbox needs. Push delivery via `users.watch` requires a Cloud Pub/Sub topic that grants `gmail-api-push@system.gserviceaccount.com` publish rights, and the watch must be renewed every 7 days [14]. For a scheduled batch job, polling `history.list` is simpler and sufficient.

```python
import base64
from email import message_from_bytes, policy
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def new_messages(creds, *, start_history_id, label_id):
    """Yield EmailMessage objects added since start_history_id. Raise KeyError to signal full resync."""
    users = build("gmail", "v1", credentials=creds).users()
    req = users.history().list(
        userId="me",
        startHistoryId=start_history_id,
        historyTypes=["messageAdded"],
        labelId=label_id,
    )
    try:
        while req is not None:
            resp = req.execute()
            for h in resp.get("history", []):
                for added in h.get("messagesAdded", []):
                    raw = (
                        users.messages()
                        .get(userId="me", id=added["message"]["id"], format="raw")
                        .execute()["raw"]
                    )
                    yield message_from_bytes(
                        base64.urlsafe_b64decode(raw), policy=policy.default
                    )
            req = users.history().list_next(
                req, resp
            )  # persist resp["historyId"] as the next cursor
    except HttpError as e:
        if e.resp.status == 404:
            raise KeyError("historyId expired; run a full sync") from e
        raise
```

Using the API also brings the Google Workspace API User Data Policy's *Limited Use* rules. Data may only serve user-visible features; it may not be used to train general AI/ML models beyond "that specific user's personalized model"; and humans may read messages only with explicit consent or for security or legal reasons [57]. Sending newsletter text to an LLM to summarize it for the same user is a user-facing feature. Pooling users' mail into a shared model is not.

### 2.3 Python libraries (checked on PyPI 2026-09-27)

| Library | Latest | Released | License | Role / notes |
|---|---|---|---|---|
| `imap-tools` | 1.15.0 | 2026-08-06 | Apache-2.0 | High-level IMAP; no external deps; `xoauth2`, IDLE, `gmail_label` search criteria [18][19] |
| `IMAPClient` | 4.1.0 | 2026-09-18 | BSD (New BSD) | Lower-level, very mature; `oauth2_login`, `gmail_search` (X-GM-RAW), `get/add_gmail_labels`, `idle` [20][21][22] |
| `imaplib` (stdlib) | n/a | n/a | PSF | Works, but raw protocol strings; use as the no-dependency fallback only |
| `google-api-python-client` | 2.200.0 | 2026-09-01 | Apache-2.0 | Official Gmail API client [16] |
| `google-auth-oauthlib` | 1.4.1 | 2026-08-24 | Apache-2.0 | Installed-app OAuth flow for the above [17] |
| `simplegmail` | 5.0.0 | 2026-08-17 | MIT | Thin Gmail API wrapper (`client_secret.json` → `gmail_token.json`); its README warns about the 7-day Testing expiry [23][24] |
| `mail-parser` | 4.6.5 | 2026-09-10 | Apache-2.0 | Forensic-grade parser on top of stdlib `email`; overkill here, but useful for defect detection [25][26] |

The stdlib `email` package with `policy=policy.default` returns `EmailMessage` objects with RFC 5322/2047-decoded header objects and `get_body(preferencelist=("html", "plain"))`. That covers most of what the third-party parsers add [32]. Use it and skip `mail-parser` by default.

## 3. Routing per tracked topic

- **Plus-addressing.** Gmail ignores everything between `+` and `@` for delivery, so `watch+anything@example.com` lands in the same inbox [27]. Filter on `deliveredto:` rather than `to:`, because the visible `To` can differ from the delivery address [27][28]. Some signup forms reject `+`. Where they do, fall back to routing by sender or `List-Id`.
- **Tag per subscription, not per topic.** A newsletter usually spans several tracked subject areas. Tagging the address with the *source* (`watch+tldr-ai@…`) gives a stable source key, reveals which list leaked or sold the address, and lets the matcher assign items to topics from their content. The spec file can still declare "source X feeds topics A and B" as a prior.
- **Filter → label → folder.** A Gmail filter (`deliveredto:watch+tldr-ai@example.com` → label `veille/tldr-ai`, skip inbox) makes each source its own IMAP folder, so each folder has its own UID cursor [15]. Creating filters programmatically through the API needs the restricted `gmail.settings.basic` scope [7], so on the IMAP path the package should generate filter criteria for the user to paste into Gmail, or just search with `X-GM-RAW` / `gmail_search` and skip labels entirely [15][21].
- **Source identity from headers.** `List-Id: Name <label.namespace>` exists precisely so software can "reliably identify messages that belong to a particular mailing list", and it survives changes of host or software [30]. RFC 2369 defines `List-Unsubscribe`, `List-Subscribe`, `List-Archive` and others as comma-separated, angle-bracketed URLs in preference order [29]. RFC 8058 adds `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, which must be DKIM-signed [31]. Recommended source key: `List-Id` if present, otherwise the normalized `From` address. The presence of `List-Unsubscribe` is a good "this is a newsletter, not personal mail" signal. `List-Archive`, when present, often points to a web version worth fetching instead of parsing the email.

## 4. Parsing HTML newsletters into items

### 4.1 Tools

| Tool | Latest | License | Use |
|---|---|---|---|
| `selectolax` | 0.4.12 (2026-09-18) | MIT | Fast HTML parsing and CSS selection (Lexbor); the default parser [33] |
| `beautifulsoup4` | 4.15.0 (2026-06-07) | MIT | Forgiving and familiar; slower; good fallback [34] |
| `markdownify` | 1.2.3 (2026-06-30) | MIT | HTML → Markdown, keeps links; best for LLM-friendly item bodies [35] |
| `inscriptis` | 2.7.4 (2026-08-10) | Apache-2.0 | Layout-aware HTML → text (handles table layouts well) [37] |
| `trafilatura` | 2.2.0 (2026-07-31) | Apache-2.0 | Main-content extraction: `extract(html, output_format="markdown", include_links=True)`; best on the *web version* of a post, weaker on table-heavy email layouts [38][39] |
| `html2text` | 2025.4.15 | **GPL-3.0-or-later** | Works well, but its license contaminates a permissively licensed package; avoid [36] |

### 4.2 Splitting one email into items

Newsletters fall into two shapes, and the splitter should detect which one it has:

1. **Single-article** emails (most Substack posts, essays). One email is one item. If a web version exists (a "view online" link or `List-Archive`), store that canonical URL and optionally run `trafilatura` on it, which gives cleaner text with no tracking.
2. **Link roundups** (TLDR-style, "this week in X"). Split on block boundaries (`h1`–`h3`, `hr`, top-level table rows or `td` blocks that contain a heading or bold lead-in plus at least one outbound link). Each block becomes an item: title (heading or first link text), body (markdownified block) and primary link (the first non-boilerplate link).

Drop boilerplate links before choosing a primary link: anything matching the `List-Unsubscribe` URLs, "view in browser", preference centers, social profile links, and sponsor blocks (headings such as "sponsor" or "presented by"). Give each item a key like `(source_key, message_id, block_index)` and use the unwrapped canonical URL as the cross-source dedup key, so the same arXiv paper seen in three newsletters becomes one entity update.

```python
from email import policy
from email.message import EmailMessage
from selectolax.parser import HTMLParser


def envelope(msg: EmailMessage) -> dict:
    body = msg.get_body(preferencelist=("html", "plain"))
    return {
        "source_key": str(msg.get("List-Id") or msg["From"].addresses[0].addr_spec),
        "message_id": str(msg["Message-ID"]),
        "subject": str(msg["Subject"]),
        "date": msg["Date"].datetime if msg["Date"] else None,
        "unsubscribe": str(msg.get("List-Unsubscribe", "")),
        "html": body.get_content()
        if body and body.get_content_type() == "text/html"
        else None,
        "text": body.get_content()
        if body and body.get_content_type() == "text/plain"
        else None,
    }


def anchors(html: str):
    for a in HTMLParser(html).css("a[href]"):
        yield a.text(strip=True), a.attributes["href"]
```

### 4.3 Unwrapping tracking redirects

Email service providers (ESPs) rewrite every link to go through a click-tracking server. The formats differ in whether the destination is *inside* the URL:

- **Substack.** Two formats are in circulation. The Mailgun-style `email.mg*.substack.com/c/<blob>` is zlib-compressed and then base64url-encoded, with the destination in the `l` field [41]. The newer `substack.com/redirect/2/eyJ…` begins with `eyJ`, the base64 of `{"`, which means a base64url JSON payload [42]. The payload also identifies the recipient [40][41].
- **Kit (ConvertKit).** `click.convertkit-mail.com/<a>/<b>/<c>`, where `c` is the base64 destination. Kit actually routes server-side, and `a` identifies the subscriber [40].
- **Mailchimp.** `…list-manage.com/track/click?u=…&id=…&e=…` is opaque. The destination is stored server-side, and `e` is a subscriber ID that stays constant across issues [40][43].
- **beehiiv.** `link.mail.beehiiv.com/ls/click?…` (or a publication's branded tracking domain) is opaque as well [44].
- **Google-style wrappers** (`google.com/url?q=…`, as seen in Google Alerts mail) carry the destination as a plain query parameter.

Recommended algorithm, cheapest and most private first:

1. **Decode offline.** For each path segment and query value longer than about 16 characters, try base64url decoding (and zlib decompression). If the result contains an `http(s)://` URL, take it. Also check plain query parameters (`q`, `url`, `u`, `l`, `redirect`). This never contacts the ESP.
2. **Follow as a bounded fallback** for opaque hosts on an allowlist (known ESP tracking domains): send HEAD (or GET if HEAD is rejected) with redirects disabled, read `Location`, and repeat for at most about 5 hops with a short timeout. Doing this registers a click attributed to the dedicated inbox [40][41]. That is acceptable for a dedicated inbox, but it skews the publisher's analytics, so make it opt-in per source (`resolve_redirects=`) and cache results by tracking URL.
3. **Never** resolve anything that matches `List-Unsubscribe`. RFC 8058 exists precisely because automated fetches of such URLs unsubscribe people by accident [31].
4. **Normalize** the result: drop `utm_*` and similar trackers and canonicalize. `courlan` (Apache-2.0, 1.4.0 from 2026-06) does this (`check_url` strips `utm_source`) [45][46]. A 20-line stdlib equivalent avoids the dependency. `unshortenit` (last release 2018) is abandoned [47].

```python
import base64, json, re, zlib
from urllib.parse import urlsplit, parse_qs

_URL = re.compile(r"https?://[^\s\"'<>\\]+")
_PLAIN_KEYS = ("q", "url", "u", "l", "redirect", "target")


def decode_embedded_url(url: str) -> str | None:
    """Recover a redirect's destination from the URL itself, without any network call."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    for key in _PLAIN_KEYS:
        for v in query.get(key, []):
            if v.startswith(("http://", "https://")):
                return v
    candidates = parts.path.split("/") + [v for vs in query.values() for v in vs]
    for seg in (c.split(".")[0] for c in candidates if len(c) >= 16):
        try:
            raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
        except ValueError:
            continue
        for blob in (raw, _inflate(raw)):
            if blob and (m := _URL.search(blob.decode("utf-8", "ignore"))):
                return m.group(0)
    return None


def _inflate(b: bytes) -> bytes | None:
    try:
        return zlib.decompress(b)
    except zlib.error:
        return None
```

## 5. Double opt-in confirmation emails

Almost every newsletter sends a confirmation link, and the subscription does not exist until someone clicks it. Kill the Newsletter's approach is instructive: it does not auto-click; the confirmation just appears as a feed entry for the human to open, and reply-to-confirm flows are unsupported [48].

Recommended policy (a keyword seam, `confirm_policy=`, defaulting to `"surface"`):

- **`surface` (default).** Detect confirmation mail (subject or body phrases such as "confirm your subscription", arriving from a sender with no prior items) and raise a "pending confirmation" record that the agent shows to the user with the link.
- **`auto` (opt-in).** Click only when all of these hold: the package logged a subscribe action for that source within the last N hours; the sender domain matches the source declared in the spec; the link host is the sender's domain or a known ESP; the request is a single HTTPS GET with no form submission, credentials or cookies; and every confirmation is logged. This blocks the main abuse, where a third party subscribes the dedicated inbox to lists it never asked for, and it avoids blindly GET-ing URLs, the failure mode RFC 8058 describes [31].
- Never auto-reply to confirm, and never click anything in mail from unknown senders.

## 6. Alternatives to reading Gmail

- **Kill the Newsletter.** Turns an email address into an Atom feed. MIT license, self-hostable, no tracking, with entries older than one month deleted [48][49]. This is the zero-code route: newsletters become ordinary feeds, and the package's RSS ingester handles them. The costs are a third-party dependency (unless self-hosted), HTML only in the feed (no `List-Id` or raw headers), and the limitations on confirmations described above.
- **Fastmail (JMAP).** A paid mailbox with a first-class API: JMAP with bearer API tokens, plus IMAP app passwords and OAuth [50]. The Python client `jmapc` 0.3.0 (2026-05) is GPL-3.0 and still Beta [51]. For a permissive package, either talk JMAP over plain HTTP JSON yourself, or use Fastmail through the default IMAP path, which needs no new code.
- **Cloudflare Email Routing + Email Workers.** Free on all plans, but the domain must use Cloudflare DNS [53][54]. A Worker's `email()` handler receives the raw MIME stream and headers, can forward or reject, and the docs show a 25 MiB size guard [52]. The Worker would write raw messages to a store (for example R2 or KV), and the package would pull from it, so no public endpoint is needed on the user's machine. This needs a domain and a small JS deployment, but you get a real address per topic or source with no mailbox at all.
- **Mailgun inbound routes.** MX to Mailgun, with route filters that forward parsed UTF-8 JSON to a webhook [55]. `store()` keeps messages for up to 3 days, retrievable via the Events API, which makes a **pull** model possible without a webhook [56]. It is keyed, and free-tier route limits apply.
- **Any IMAP mailbox** (including self-hosted). Handled by the default path with no special code, which is the strongest argument for making IMAP the default seam.

## 7. Legal and terms-of-service notes

- **Google terms.** Google's Terms prohibit automated access "in violation of the machine-readable instructions" and "bypassing our systems or protective measures" [58]. IMAP with an app password and the Gmail API are both documented, sanctioned interfaces [4][15]. Scraping the Gmail web UI is not, so never do it. API use additionally falls under the Limited Use policy (section 2.2) [57].
- **Copyright.** Newsletter text is copyrighted by its author. For a published digest, the fair-use factors favor transformative, factual, short uses that do not substitute for the original [59]. So: summarize, quote briefly, attribute, and link to the canonical (unwrapped) URL. Do not republish whole issues or paywalled posts. In the EU, the DSM Directive Art. 4 text-and-data-mining exception covers *analysis* of lawfully accessed works unless rights are reserved in machine-readable form. That exception covers mining, not redistribution in digests [60].
- **GDPR.** Tracking links and headers contain the dedicated inbox's own address, and newsletters mention third parties. The household exemption applies only to a natural person acting purely privately. Organizations running the tool are controllers [61][62]. Mitigations: strip tracking tokens before storage (section 4.3), keep raw MIME under a retention limit, and do not store full raw mail by default.
- **CAN-SPAM and similar anti-spam laws** regulate senders, so they are irrelevant to reading. RFC 8058 still matters operationally, as noted above [31].

## 8. Comparison

| Option | Keys / accounts | Setup effort | Incremental sync | Routing | Python deps (license) | Cost |
|---|---|---|---|---|---|---|
| **Gmail IMAP + app password** | Dedicated Gmail with 2SV + app password | Low | UIDVALIDITY + UID per label folder | Plus-address + filter → label; X-GM-RAW | `imap-tools` (Apache-2.0), stdlib | Free |
| Gmail API (own GCP project) | GCP project, OAuth client, consent screen in Production | Medium-high | `history.list` cursor (2 units/call) | Labels via API; filters need restricted scope | `google-api-python-client`, `google-auth-oauthlib` (Apache-2.0) | Free |
| Gmail IMAP + XOAUTH2 | GCP project + `mail.google.com` scope | High | As IMAP | As IMAP | `imap-tools` / `IMAPClient` + `google-auth` | Free |
| Kill the Newsletter | None (public instance) | Very low | Feed entries | One address per feed | Feed parser only | Free |
| Fastmail JMAP | Paid account + API token | Low | JMAP state strings | Masked/plus addresses, rules | HTTP JSON (or `jmapc`, GPL-3.0) | Paid |
| Cloudflare Email Workers | Domain on Cloudflare DNS | Medium (JS Worker) | Your store's keys | Any address on the domain | Store client only | Free tier |
| Mailgun inbound | Mailgun account + MX | Medium | Events API cursor | Route filters | HTTP client | Free tier / paid |

## 9. Recommendation

**Zero-key default.** Use IMAP against a dedicated inbox with an app password, through `imap-tools`. The steps:

1. Give each subscription a plus-address.
2. Have the user paste one Gmail filter per source that applies a `veille/<source>` label.
3. Keep a `(UIDVALIDITY, last UID)` cursor per label folder in the package's key-value store.
4. Parse with stdlib `email` (`policy.default`), `selectolax` and `markdownify`.
5. Identify sources by `List-Id` or the sender.
6. Unwrap links offline first, with redirect-following opt-in per source.
7. Surface confirmation emails instead of clicking them.

This works with any IMAP provider, needs no Google Cloud project, and stays within documented, sanctioned interfaces. The dependencies are small and permissively licensed.

**Seam.** Expose the mailbox as one keyword argument, for example `mail_source=ImapSource(...)`, behind a tiny protocol that yields `(cursor, EmailMessage)`. The alternatives already exist to point at: `GmailApiSource` (optional `[gmail]` extra), `FeedSource` (Kill the Newsletter via the RSS ingester), and a `StoreSource` that reads raw MIME dropped by a Cloudflare Worker or Mailgun `store()`.

**Stronger optional alternative.** Use the Gmail API with a bring-your-own OAuth client whose consent screen is set to *In production*, with `gmail.readonly` (or `gmail.modify` if the tool should archive or label processed mail) and `history.list` cursors. Choose it when the user wants exact change tracking, label management, or push via Pub/Sub. Document the 7-day Testing trap prominently, and never ship a shared OAuth client: restricted scopes would then require CASA verification [8][10]. For users who would rather not use Google at all, the best fit is Fastmail (JMAP or IMAP) or a Cloudflare-routed domain.

## REFERENCES

[1] Google. Transition from less secure apps to OAuth (Google Workspace Admin Help). 2024. [knowledge.workspace.google.com](https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth)
[2] Google Workspace Updates. Beginning September 30, 2024: third-party apps that use only a password to access Google Accounts and Google Sync will no longer be supported. 2023. [workspaceupdates.googleblog.com](https://workspaceupdates.googleblog.com/2023/09/winding-down-google-sync-and-less-secure-apps-support.html)
[3] Google. Sign in with app passwords (Google Account Help). 2026. [support.google.com](https://support.google.com/accounts/answer/185833?hl=en)
[4] Nylas. Gmail App Passwords: Setup and Gotchas. 2026. [cli.nylas.com](https://cli.nylas.com/guides/gmail-app-password-setup)
[5] Mailbird. Gmail OAuth 2.0 Changes 2026: What Gmail Users Need to Know About App Passwords and Secure Access. 2026. [getmailbird.com](https://www.getmailbird.com/gmail-oauth-changes-app-password-phase-out/)
[6] Google. OAuth 2.0 Mechanism (XOAUTH2) for Gmail IMAP/SMTP. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol)
[7] Google. Choose Gmail API scopes. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/api/auth/scopes)
[8] Google. Restricted scope verification. 2026. [developers.google.com](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
[9] Nylas. Google verification and security assessment guide. 2026. [developer.nylas.com](https://developer.nylas.com/docs/provider-guides/google/google-verification-security-assessment-guide/)
[10] ko-hi (DEV Community). Google's OAuth 'Testing' mode expires refresh tokens in 7 days. Publish the consent screen before you schedule anything. 2026. [dev.to](https://dev.to/ko-hi/googles-oauth-testing-mode-expires-refresh-tokens-in-7-days-publish-the-consent-screen-before-24hm)
[11] Google. Manage App Audience (Google Cloud Console Help). 2026. [support.google.com](https://support.google.com/cloud/answer/15549945?hl=en)
[12] Google. Method: users.history.list (Gmail API). 2026. [developers.google.com](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)
[13] Google. Gmail API usage limits. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/api/reference/quota)
[14] Google. Configure push notifications with the Gmail API. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/api/guides/push)
[15] Google. Gmail IMAP extensions. 2026. [developers.google.com](https://developers.google.com/workspace/gmail/imap/imap-extensions)
[16] PyPI. google-api-python-client 2.200.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/google-api-python-client/json)
[17] PyPI. google-auth-oauthlib 1.4.1 metadata. 2026. [pypi.org](https://pypi.org/pypi/google-auth-oauthlib/json)
[18] ikvk. imap_tools (GitHub repository). 2026. [github.com](https://github.com/ikvk/imap_tools)
[19] PyPI. imap-tools 1.15.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/imap-tools/json)
[20] mjs. IMAPClient (GitHub repository). 2026. [github.com](https://github.com/mjs/imapclient)
[21] IMAPClient. API reference. 2026. [imapclient.readthedocs.io](https://imapclient.readthedocs.io/en/master/api.html)
[22] PyPI. IMAPClient 4.1.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/IMAPClient/json)
[23] jeremyephron. simplegmail (GitHub repository). 2026. [github.com](https://github.com/jeremyephron/simplegmail)
[24] PyPI. simplegmail 5.0.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/simplegmail/json)
[25] SpamScope. mail-parser (GitHub repository). 2026. [github.com](https://github.com/SpamScope/mail-parser)
[26] PyPI. mail-parser 4.6.5 metadata. 2026. [pypi.org](https://pypi.org/pypi/mail-parser/json)
[27] Email Ferret. Email Aliases and Plus Addressing: Stop Spam. 2026. [emailferret.io](https://emailferret.io/guides/gmail-filters-labels/email-aliases-plus-addressing)
[28] Google. Searching for messages (Gmail API filtering guide). 2026. [developers.google.com](https://developers.google.com/gmail/api/guides/filtering)
[29] Neufeld G, Baer J. RFC 2369: The Use of URLs as Meta-Syntax for Core Mail List Commands and their Transport through Message Header Fields. 1998. [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc2369.html)
[30] Chandhok R, Wenger G. RFC 2919: List-Id: A Structured Field and Namespace for the Identification of Mailing Lists. 2001. [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc2919.html)
[31] Levine J, Herkula T. RFC 8058: Signaling One-Click Functionality for List Email Headers. 2017. [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc8058.html)
[32] Python Software Foundation. email.policy: Policy Objects. 2026. [docs.python.org](https://docs.python.org/3/library/email.policy.html)
[33] PyPI. selectolax 0.4.12 metadata. 2026. [pypi.org](https://pypi.org/pypi/selectolax/json)
[34] PyPI. beautifulsoup4 4.15.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/beautifulsoup4/json)
[35] PyPI. markdownify 1.2.3 metadata. 2026. [pypi.org](https://pypi.org/pypi/markdownify/json)
[36] PyPI. html2text 2025.4.15 metadata. 2025. [pypi.org](https://pypi.org/pypi/html2text/json)
[37] PyPI. inscriptis 2.7.4 metadata. 2026. [pypi.org](https://pypi.org/pypi/inscriptis/json)
[38] Barbaresi A. Trafilatura: With Python. 2026. [trafilatura.readthedocs.io](https://trafilatura.readthedocs.io/en/latest/usage-python.html)
[39] PyPI. trafilatura 2.2.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/trafilatura/json)
[40] Tan B. What's in email tracking links and pixels? [bengtan.com](https://bengtan.com/blog/whats-in-email-tracking-links-and-pixels/)
[41] Tan B. Investigating Substack/Mailgun tracking links. [bengtan.com](https://bengtan.com/blog/investigating-substack-mailgun-tracking/)
[42] SaurabhJalendra. Daily QA (2026-09-24): PASS_WITH_WARNINGS, Email_daily_newsletter_summary issue 223. 2026. [github.com](https://github.com/SaurabhJalendra/Email_daily_newsletter_summary/issues/223)
[43] Mailchimp. Use Click Tracking in Emails. 2026. [mailchimp.com](https://mailchimp.com/help/enable-and-view-click-tracking/)
[44] beehiiv. How to use a branded link for your publication. 2026. [beehiiv.com](https://www.beehiiv.com/support/article/29885524124183-how-to-use-a-branded-link-for-your-publication)
[45] Barbaresi A. coURLan (GitHub repository). 2026. [github.com](https://github.com/adbar/courlan)
[46] PyPI. courlan 1.4.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/courlan/json)
[47] PyPI. unshortenit 0.4.0 metadata. 2018. [pypi.org](https://pypi.org/pypi/unshortenit/json)
[48] Facchinetti L. Kill the Newsletter! 2026. [kill-the-newsletter.com](https://kill-the-newsletter.com/)
[49] Facchinetti L. kill-the-newsletter (GitHub repository). 2026. [github.com](https://github.com/leafac/kill-the-newsletter)
[50] Fastmail. Fastmail for developers. 2026. [fastmail.com](https://www.fastmail.com/dev/)
[51] PyPI. jmapc 0.3.0 metadata. 2026. [pypi.org](https://pypi.org/pypi/jmapc/json)
[52] Cloudflare. Email Workers. 2026. [developers.cloudflare.com](https://developers.cloudflare.com/email-routing/email-workers/)
[53] Cloudflare. Enable Email Routing. 2026. [developers.cloudflare.com](https://developers.cloudflare.com/email-routing/get-started/enable-email-routing/)
[54] Cloudflare. Email Routing overview. 2026. [developers.cloudflare.com](https://developers.cloudflare.com/email-routing/)
[55] Mailgun. Inbound Email Routing. 2026. [mailgun.com](https://www.mailgun.com/features/inbound-email-routing/)
[56] Mailgun. Store(): A Temporary Mailbox For All Your Incoming Email. [mailgun.com](https://www.mailgun.com/blog/product/store-a-temporary-mailbox-for-all-your-incoming-email/)
[57] Google. Google Workspace API User Data and Developer Policy. 2026. [developers.google.com](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
[58] Google. Google Terms of Service. 2026. [policies.google.com](https://policies.google.com/terms?hl=en)
[59] U.S. Copyright Office. Fair Use Index. 2026. [copyright.gov](https://www.copyright.gov/fair-use/)
[60] Kluwer Copyright Blog. The New Copyright Directive: Text and Data Mining (Articles 3 and 4). 2019. [legalblogs.wolterskluwer.com](https://legalblogs.wolterskluwer.com/copyright-blog/the-new-copyright-directive-text-and-data-mining-articles-3-and-4/)
[61] Intersoft Consulting. Art. 2 GDPR: Material scope. 2016. [gdpr-info.eu](https://gdpr-info.eu/art-2-gdpr/)
[62] Data Protection Commission (Ireland). What is the household exemption? [dataprotection.ie](https://www.dataprotection.ie/en/faqs/general/what-household-exemption)
