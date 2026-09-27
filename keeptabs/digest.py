"""Answering "what's new", writing it up, and delivering it.

A digest is data first (:func:`whats_new` returns a JSON-ready dict) and text
second (a summarizer turns that dict into Markdown).

What the items say was written by other people. :func:`render_markdown` builds
every link from a stored item's URL and escapes titles and summaries, so fetched
text cannot add a link, a tag or a mention of its own.
"""

import json
import os
import re
import urllib.request
from datetime import timedelta

from keeptabs.util import isoformat, parse_duration, timestamp_key, to_datetime, utcnow

DEFAULT_LOOKBACK = "7d"
OTHER_SECTION = "other"
SUMMARY_CHARS = 280
SLACK_WEBHOOK_ENV_VAR = "KEEPTABS_SLACK_WEBHOOK_URL"
SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/"

_MARKDOWN_SPECIALS = re.compile(r"([\\\[\]`*_|])")
_HTML_SPECIALS = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
_BARE_AMPERSAND = re.compile(r"&(?!(?:amp|lt|gt);)")
_URL_UNSAFE = str.maketrans(
    {"(": "%28", ")": "%29", " ": "%20", "<": "%3C", ">": "%3E", '"': "%22"}
)


def escape_text(text: str) -> str:
    """Text that renders as itself, in Markdown and in HTML: no link, tag,
    mention or emphasis of its own.

    >>> print(escape_text('Sprout <!channel> [click](https://evil.example) & co'))
    Sprout &lt;!channel&gt; \\[click\\](https://evil.example) &amp; co
    """
    text = re.sub(r"[&<>]", lambda m: _HTML_SPECIALS[m.group()], text or "")
    return _MARKDOWN_SPECIALS.sub(r"\\\1", text)


def _link(title, url):
    if not url.startswith(("http://", "https://")):
        return escape_text(title or url)
    return f"[{escape_text(title or url)}]({url.translate(_URL_UNSAFE)})"


def _recency_key(item):
    return item.get("published") or item.get("acquired") or ""


def whats_new(spec: dict, mall: dict, *, since=None, max_items=None, now=None) -> dict:
    """The items acquired since ``since``, grouped by subtopic, best first.

    ``since`` is a time, or a duration ago (``'3d'``). It defaults to the time of
    the last digest, or to a week ago when there has been none. What the last
    digest already reported is not reported again.
    """
    now = to_datetime(now) if now else utcnow()
    last_digest = mall["state"].get("digest", {}).get("last_digest")
    after_last_digest = since is None and last_digest is not None
    since = to_datetime(since or last_digest or DEFAULT_LOOKBACK, now=now)

    def is_fresh(when):
        when = to_datetime(when)
        return when > since if after_last_digest else when >= since

    max_items = max_items or spec["digest"]["max_items"]
    fresh = [item for item in mall["items"].values() if is_fresh(item["acquired"])]
    fresh.sort(
        key=lambda item: (item.get("score", 0), _recency_key(item)), reverse=True
    )
    shown = fresh[:max_items]
    titles = {subtopic["id"]: subtopic["title"] for subtopic in spec["subtopics"]}
    sections = {}
    for item in shown:
        section = next(
            (s for s in item.get("subtopics", []) if s in titles), OTHER_SECTION
        )
        sections.setdefault(section, []).append(item)
    order = [s for s in titles if s in sections] + (
        [OTHER_SECTION] if OTHER_SECTION in sections else []
    )
    entities = [
        {
            k: record.get(k)
            for k in (
                "id",
                "name",
                "kind",
                "url",
                "mentions",
                "first_seen",
                "last_seen",
            )
        }
        for record in mall["entities"].values()
        if is_fresh(record["last_seen"])
    ]
    failing = [
        {
            "source": key.removeprefix("source--"),
            "error": state.get("last_error"),
            "failures": state["failures"],
        }
        for key, state in mall["state"].items()
        if key.startswith("source--") and state.get("failures")
    ]
    return {
        "watch": spec["id"],
        "title": spec["title"],
        "since": isoformat(since),
        "until": isoformat(now),
        "total_new": len(fresh),
        "shown": len(shown),
        "sections": [
            {"id": s, "title": titles.get(s, "Other"), "items": sections[s]}
            for s in order
        ],
        "new_entities": [e for e in entities if is_fresh(e["first_seen"])],
        "active_entities": sorted(entities, key=lambda e: -(e["mentions"] or 0)),
        "failing_sources": failing,
    }


def render_markdown(digest: dict) -> str:
    """A digest as Markdown, with no model involved.

    >>> print(render_markdown({'title': 'Gen AI', 'since': '2026-01-01T00:00:00+00:00',
    ...     'until': '2026-01-08T00:00:00+00:00', 'total_new': 1, 'shown': 1, 'sections': [
    ...     {'id': 'video', 'title': 'Video', 'items': [{'title': 'A model', 'url': 'https://example.com/a',
    ...     'summary': 'It generates.', 'published': '2026-01-05T00:00:00+00:00', 'source': 'blog'}]}],
    ...     'new_entities': [], 'active_entities': [], 'failing_sources': []}))
    # What's new: Gen AI
    <BLANKLINE>
    2026-01-01 to 2026-01-08. 1 new item.
    <BLANKLINE>
    ## Video
    <BLANKLINE>
    - [A model](https://example.com/a) (blog, 2026-01-05). It generates.
    """
    count = digest["total_new"]
    lines = [
        f"# What's new: {digest['title']}",
        "",
        f"{digest['since'][:10]} to {digest['until'][:10]}. {count} new item{'s' if count != 1 else ''}."
        + (f" Showing the top {digest['shown']}." if digest["shown"] < count else ""),
    ]
    if not count:
        lines += ["", "Nothing new in this period."]
    for section in digest["sections"]:
        lines += ["", f"## {section['title']}", ""]
        for item in section["items"]:
            head = _link(item.get("title"), item.get("url") or "")
            facts = ", ".join(
                x for x in (item.get("source"), (item.get("published") or "")[:10]) if x
            )
            summary = " ".join((item.get("summary") or "").split())
            if len(summary) > SUMMARY_CHARS:
                summary = summary[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
            lines.append(
                f"- {head} ({escape_text(facts)})."
                + (f" {escape_text(summary)}" if summary else "")
            )
    if digest["new_entities"]:
        lines += ["", "## First seen in this period", ""]
        lines += [
            f"- {escape_text(str(e['name']))} ({escape_text(str(e['kind']))})"
            for e in digest["new_entities"]
        ]
    if digest["failing_sources"]:
        lines += ["", "## Sources that are failing", ""]
        lines += [
            f"- {f['source']}: {escape_text(str(f['error']))} ({f['failures']} in a row)"
            for f in digest["failing_sources"]
        ]
    return "\n".join(lines)


def _send_with_correspond(ref, text, *, title, dry_run):
    try:
        from correspond import tools as correspond_tools
    except ImportError as error:
        raise RuntimeError(
            f"Sending to {ref!r} goes through the 'correspond' package. Install it with: pip install 'keeptabs[mail]'."
        ) from error
    return correspond_tools.send(ref, text, title=title, dry_run=dry_run)


def _send_to_slack(ref, text, *, title, dry_run):
    """Post to a Slack incoming webhook, whose URL is read from the environment.

    ``slack:`` reads ``KEEPTABS_SLACK_WEBHOOK_URL``; ``slack:team`` reads
    ``KEEPTABS_SLACK_WEBHOOK_URL_TEAM``. No other variable can be named, and the
    value is never shown.
    """
    name = ref.partition(":")[2].strip()
    if name and not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError(
            f"Not a Slack channel reference: {ref!r}. Use 'slack:' or 'slack:<name>'."
        )
    variable = (
        f"{SLACK_WEBHOOK_ENV_VAR}_{name.upper()}" if name else SLACK_WEBHOOK_ENV_VAR
    )
    url = os.environ.get(variable, "")
    if not url.startswith(SLACK_WEBHOOK_PREFIX):
        raise RuntimeError(
            f"No Slack webhook: set the environment variable {variable} to an incoming-webhook URL, "
            f"which starts with {SLACK_WEBHOOK_PREFIX} "
            "(https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks)."
        )
    if dry_run:
        return {"ok": True, "dry_run": True, "ref": ref, "chars": len(text)}
    # no mention, no markup: item text is escaped already, this covers the rest
    safe = _BARE_AMPERSAND.sub("&amp;", text).replace("<", "&lt;").replace(">", "&gt;")
    payload = json.dumps({"text": f"*{title}*\n{safe}"}).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            return {"ok": reply.status == 200, "ref": ref}
    except Exception as error:
        raise RuntimeError(
            f"Slack refused the message ({type(error).__name__})."
        ) from None


DEFAULT_SENDERS = {
    "email": _send_with_correspond,
    "github": _send_with_correspond,
    "ntfy": _send_with_correspond,
    "telegram": _send_with_correspond,
    "slack": _send_to_slack,
}


def deliver(text: str, channels, *, title: str, dry_run=True, senders=None) -> list:
    """Send a digest to each channel reference, such as ``email:me@example.org``,
    ``github:owner/repo#12`` (a discussion) or ``slack:``.

    Dry-run by default: a real send reaches people and cannot be unsent. One
    failing channel does not stop the others.
    """
    senders = {**DEFAULT_SENDERS, **(senders or {})}
    results = []
    for ref in channels:
        scheme = ref.partition(":")[0]
        try:
            if scheme not in senders:
                raise RuntimeError(
                    f"No sender for {scheme!r} channels. Known: {', '.join(sorted(senders))}."
                )
            outcome = senders[scheme](ref, text, title=title, dry_run=dry_run)
            ok = outcome.get("ok", True) if isinstance(outcome, dict) else True
            results.append(
                {"channel": ref, "ok": ok, "dry_run": dry_run, "outcome": outcome}
            )
        except Exception as error:
            results.append(
                {
                    "channel": ref,
                    "ok": False,
                    "dry_run": dry_run,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return results


def make_digest(
    spec,
    mall,
    *,
    since=None,
    now=None,
    summarizer=None,
    send=False,
    senders=None,
    mark_reported=None,
) -> dict:
    """Build a digest, store it, and deliver it (for real only when ``send``).

    ``mark_reported`` says whether the items count as reported from now on, so the
    next digest leaves them out. It defaults to ``send``: a dry run changes nothing,
    and can be followed by the real send of the same digest.
    """
    mark_reported = send if mark_reported is None else mark_reported
    now = to_datetime(now) if now else utcnow()
    data = whats_new(spec, mall, since=since, now=now)
    text = (summarizer or render_markdown)(data)
    title = f"What's new: {spec['title']} ({data['until'][:10]})"
    deliveries = deliver(
        text, spec["digest"]["channels"], title=title, dry_run=not send, senders=senders
    )
    key = timestamp_key(now) + ("" if mark_reported else "--dry-run")
    record = {
        "watch": spec["id"],
        "at": isoformat(now),
        "title": title,
        "text": text,
        "deliveries": deliveries,
        "since": data["since"],
        "total_new": data["total_new"],
        "item_ids": [
            item["id"] for section in data["sections"] for item in section["items"]
        ],
    }
    record["reported"] = mark_reported
    mall["digests"][key] = record
    if mark_reported:
        period = parse_duration(spec["digest"]["cadence"])
        mall["state"]["digest"] = {
            "last_digest": isoformat(now),
            "next_due": isoformat(now + timedelta(seconds=period)),
        }
    return {"key": key, **record}


def scheduled_digest(*, summarizer=None, senders=None):
    """The ``on_digest_due`` callback for :func:`keeptabs.engine.tick`.

    It sends for real only when the spec says ``digest.auto_send: true``, and it
    skips a period with nothing new.
    """

    def on_digest_due(spec, mall, now):
        if not whats_new(spec, mall, now=now)["total_new"]:
            period = parse_duration(spec["digest"]["cadence"])
            previous = mall["state"].get("digest", {})
            mall["state"]["digest"] = {
                **previous,
                "next_due": isoformat(now + timedelta(seconds=period)),
            }
            return {"watch": spec["id"], "skipped": "nothing new"}
        digest = make_digest(
            spec, mall, now=now, summarizer=summarizer, senders=senders,
            send=spec["digest"]["auto_send"], mark_reported=True,
        )  # fmt: skip
        return {
            k: digest[k] for k in ("watch", "key", "title", "total_new", "deliveries")
        }

    return on_digest_due
