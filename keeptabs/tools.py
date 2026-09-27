"""The operations of keeptabs, as plain functions: JSON-able arguments in, a
JSON-ready dict out.

This module is the single list every surface is built from (:data:`TOOLS`). It
knows nothing about the command line, MCP or HTTP; a wrapper references
``keeptabs.tools:tick`` and gets a dict back.
"""

import json
import sys
from importlib.resources import files
from pathlib import Path

import yaml

from keeptabs import digest as _digest
from keeptabs import engine
from keeptabs.matching import keyword_matcher
from keeptabs.spec import (
    SpecError,
    blocked_source_ids,
    normalize_source,
    normalize_spec,
    target_field,
)
from keeptabs.stores import spec_store, watch_mall
from keeptabs.util import (
    ROOTDIR_ENV_VAR,
    isoformat,
    rootdir as _rootdir,
    slug,
    to_datetime,
    utcnow,
)

EXAMPLES_DIR = "data/examples"
DEFAULT_TICK_EVERY_MINUTES = 30
LAUNCHD_LABEL = "com.keeptabs.tick"
LAUNCHD_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{arguments}
    </array>
    <key>StartInterval</key><integer>{seconds}</integer>
    <key>RunAtLoad</key><true/>
</dict>
</plist>"""
SYSTEMD_TEMPLATE = """# keeptabs.service
[Unit]
Description=keeptabs tick

[Service]
Type=oneshot
ExecStart={command}

# keeptabs.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec={minutes}min
Persistent=true

[Install]
WantedBy=timers.target"""


def components(rootdir=None) -> dict:
    """What every tool runs with: the stores, the matcher, the summarizer, the senders.

    This is the one place to change when a surface should run on other stores or
    with a model-based matcher or summarizer: every tool below reads it.
    """
    return {
        "specs": spec_store(rootdir),
        "malls": lambda watch_id: watch_mall(watch_id, rootdir=rootdir),
        "matcher": keyword_matcher,
        "summarizer": _digest.render_markdown,
        "senders": None,
        "lock": lambda: engine.tick_lock(rootdir),  # a new lock for each run
    }


def _load(watch_id, rootdir=None):
    specs = components(rootdir)["specs"]
    if watch_id not in specs:
        known = ", ".join(sorted(specs)) or "none yet"
        raise KeyError(
            f"No watch named {watch_id!r}. Known watches: {known}. Create one with init-watch."
        )
    return specs, normalize_spec(specs[watch_id], watch_id=watch_id)


def _save(specs, spec):
    spec = normalize_spec(spec)
    spec["updated"] = isoformat(utcnow())
    specs[spec["id"]] = spec
    return spec


def _csv(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def examples() -> dict:
    """The example watch specifications shipped with the package."""
    names = sorted(
        p.name.removesuffix(".yaml")
        for p in files("keeptabs").joinpath(EXAMPLES_DIR).iterdir()
        if p.name.endswith(".yaml")
    )
    return {"ok": True, "examples": names}


def _each_spec(specs):
    """Each watch id with its checked spec, or with the error that makes it unusable."""
    for watch_id in sorted(specs):
        try:
            yield watch_id, normalize_spec(specs[watch_id], watch_id=watch_id), None
        except Exception as error:  # one broken spec must not hide the others
            yield watch_id, None, f"{type(error).__name__}: {error}"


def watches(*, rootdir: str = None) -> dict:
    """List the watches: id, title, number of sources, and how many human actions are open. A watch whose specification cannot be read is listed with its error."""
    parts = components(rootdir)
    rows = []
    for watch_id, spec, error in _each_spec(parts["specs"]):
        if error:
            rows.append({"id": watch_id, "error": error})
            continue
        rows.append(
            {
                "id": watch_id,
                "title": spec["title"],
                "enabled": spec["enabled"],
                "sources": len(spec["sources"]),
                "blocked_sources": len(blocked_source_ids(spec)),
                "open_actions": sum(
                    a["status"] == "open" for a in spec["pending_actions"]
                ),
                "items": len(parts["malls"](watch_id)["items"]),
            }
        )
    return {
        "ok": not any("error" in row for row in rows),
        "rootdir": str(_rootdir(rootdir)),
        "watches": rows,
    }


def watch(watch_id: str, *, rootdir: str = None) -> dict:
    """Show one watch specification in full."""
    _, spec = _load(watch_id, rootdir)
    return {"ok": True, "spec": spec}


def init_watch(
    title: str,
    *,
    intent: str = "",
    example: str = None,
    spec_file: str = None,
    watch_id: str = None,
    overwrite: bool = False,
    rootdir: str = None,
) -> dict:
    """Create a watch from a vague idea (`title` and `intent`), from a shipped `example`, or from a YAML or JSON `spec_file`. Refine it afterwards with the add-* commands or edit-watch."""
    if example and spec_file:
        raise SpecError("Give an example or a spec file, not both.")
    base = {}
    if example:
        base = yaml.safe_load(
            files("keeptabs")
            .joinpath(EXAMPLES_DIR, f"{example}.yaml")
            .read_text(encoding="utf-8")
        )
    elif spec_file:
        base = yaml.safe_load(
            Path(spec_file).expanduser().read_text(encoding="utf-8")
        )  # YAML reads JSON too
    if base and not isinstance(base, dict):
        raise SpecError(
            "A spec file holds one mapping, with fields such as title, keywords and sources."
        )
    spec = {**base, "id": watch_id or slug(title), "title": title}
    if intent:
        spec["intent"] = intent
    notes = []
    digest = spec.get("digest")
    if isinstance(digest, dict) and (digest.get("auto_send") or digest.get("channels")):
        # a spec from elsewhere must not decide that this machine sends things, or to whom
        notes.append(
            f"The spec named channels for its digests ({', '.join(map(str, digest.get('channels') or [])) or 'none'}) "
            "and may have asked to send them automatically. Both were removed: set them with edit-watch if the user wants them."
        )
        spec["digest"] = {**digest, "auto_send": False, "channels": []}
    specs = components(rootdir)["specs"]
    spec = normalize_spec(spec)
    if spec["id"] in specs and not overwrite:
        raise SpecError(
            f"A watch named {spec['id']!r} exists. Pass overwrite to replace it, or edit it."
        )
    spec["created"] = isoformat(utcnow())
    return {"ok": True, "notes": notes, "spec": _save(specs, spec)}


def edit_watch(watch_id: str, patch: str, *, rootdir: str = None) -> dict:
    """Change top-level fields of a watch. `patch` is a JSON object; each key replaces that field (a null removes it). Use it for title, intent, scope, keywords, min_score, digest and enabled."""
    specs, spec = _load(watch_id, rootdir)
    try:
        changes = json.loads(patch) if isinstance(patch, str) else patch
    except json.JSONDecodeError as error:
        raise SpecError(f"The patch is not JSON: {error}.") from None
    if not isinstance(changes, dict):
        raise SpecError('The patch must be a JSON object, such as {"min_score": 2}.')
    if "id" in changes and changes["id"] != watch_id:
        raise SpecError(
            "A watch cannot be renamed by a patch: its data is stored under its id."
        )
    for key, value in changes.items():
        if value is None:
            spec.pop(key, None)
        elif isinstance(value, dict) and isinstance(spec.get(key), dict):
            spec[key] = {**spec[key], **value}
        else:
            spec[key] = value
    return {"ok": True, "spec": _save(specs, spec)}


def _upsert(records, record):
    return [r for r in records if r["id"] != record["id"]] + [record]


def add_source(
    watch_id: str,
    kind: str,
    target: str,
    *,
    title: str = None,
    cadence: str = None,
    keep_all: bool = False,
    source_id: str = None,
    rootdir: str = None,
) -> dict:
    """Add a source to a watch, or replace the one with the same id. `target` is the feed URL, the search query, the `owner/name` repository or the newsletter sender address, by `kind` (feed, arxiv, github_releases, hackernews, news_search, email; any other kind needs its own fetcher at run time). `keep_all` keeps every item without a keyword match, for a source already dedicated to the topic."""
    specs, spec = _load(watch_id, rootdir)
    source = {"kind": kind, target_field(kind): target, "keep_all": keep_all}
    source.update(
        {
            k: v
            for k, v in {"title": title, "cadence": cadence, "id": source_id}.items()
            if v
        }
    )
    source = normalize_source(source)
    spec["sources"] = _upsert(spec["sources"], source)
    _save(specs, spec)
    return {"ok": True, "source": source}


def remove_source(watch_id: str, source_id: str, *, rootdir: str = None) -> dict:
    """Remove a source from a watch. What it already acquired is kept."""
    specs, spec = _load(watch_id, rootdir)
    kept = [s for s in spec["sources"] if s["id"] != source_id]
    if len(kept) == len(spec["sources"]):
        raise KeyError(
            f"No source {source_id!r} in {watch_id!r}. Sources: {', '.join(s['id'] for s in kept)}."
        )
    spec["sources"] = kept
    _save(specs, spec)
    return {"ok": True, "removed": source_id}


def add_keywords(
    watch_id: str,
    keywords: str,
    *,
    subtopic: str = None,
    priority: str = None,
    rootdir: str = None,
) -> dict:
    """Add comma-separated keywords to a watch, or to one of its subtopics (created if missing)."""
    specs, spec = _load(watch_id, rootdir)
    if subtopic:
        subtopic_id = slug(subtopic)
        record = next(
            (s for s in spec["subtopics"] if s["id"] == subtopic_id), None
        ) or {"id": subtopic_id, "title": subtopic, "keywords": []}
        record["keywords"] = list(dict.fromkeys(record["keywords"] + _csv(keywords)))
        if priority:
            record["priority"] = priority
        spec["subtopics"] = _upsert(spec["subtopics"], record)
    else:
        spec["keywords"] = list(dict.fromkeys(spec["keywords"] + _csv(keywords)))
    spec = _save(specs, spec)
    return {"ok": True, "keywords": spec["keywords"], "subtopics": spec["subtopics"]}


def add_entity(
    watch_id: str,
    name: str,
    *,
    kind: str = "thing",
    url: str = None,
    aliases: str = None,
    note: str = None,
    rootdir: str = None,
) -> dict:
    """Track a named thing (a model, library, company, lab, person, dataset) in a watch. Items that mention it, or one of its comma-separated `aliases`, are linked to it."""
    specs, spec = _load(watch_id, rootdir)
    entity_id = slug(name)
    known = next((e for e in spec["entities"] if e["id"] == entity_id), {})
    entity = {
        **known,
        "id": entity_id,
        "name": name,
        "aliases": list(dict.fromkeys(known.get("aliases", []) + _csv(aliases))),
    }
    entity["kind"] = kind if kind != "thing" or not known else known["kind"]
    entity.update({k: v for k, v in {"url": url, "note": note}.items() if v})
    spec["entities"] = _upsert(spec["entities"], entity)
    _save(specs, spec)
    return {"ok": True, "entity": entity}


def add_action(
    watch_id: str,
    action: str,
    *,
    why: str = "",
    blocks: str = None,
    rootdir: str = None,
) -> dict:
    """Record something only the human can do (subscribe to a newsletter, provide a key). `blocks` is a comma-separated list of source ids that must not run until it is done."""
    specs, spec = _load(watch_id, rootdir)
    record = {
        "id": slug(action)[:60],
        "action": action,
        "why": why,
        "blocks": _csv(blocks),
        "status": "open",
        "asked": isoformat(utcnow()),
    }
    spec["pending_actions"] = _upsert(spec["pending_actions"], record)
    _save(specs, spec)
    return {"ok": True, "action": record}


def resolve_action(
    watch_id: str, action_id: str, *, status: str = "done", rootdir: str = None
) -> dict:
    """Mark a human action as done (or dropped), which unblocks the sources that waited on it."""
    specs, spec = _load(watch_id, rootdir)
    for action in spec["pending_actions"]:
        if action["id"] == action_id:
            action.update(status=status, resolved=isoformat(utcnow()))
            _save(specs, spec)
            return {"ok": True, "action": action}
    raise KeyError(
        f"No action {action_id!r} in {watch_id!r}. Actions: {', '.join(a['id'] for a in spec['pending_actions'])}."
    )


def pending(*, rootdir: str = None) -> dict:
    """Everything that waits on the human, across all watches."""
    actions, unreadable = [], []
    for watch_id, spec, error in _each_spec(components(rootdir)["specs"]):
        if error:
            unreadable.append({"watch": watch_id, "error": error})
            continue
        actions += [
            {"watch": watch_id, **a}
            for a in spec["pending_actions"]
            if a["status"] == "open"
        ]
    return {
        "ok": not unreadable,
        "count": len(actions),
        "actions": actions,
        "unreadable": unreadable,
    }


def _source_status(spec, source, record, blocked, now):
    if not (source["enabled"] and spec["enabled"]):
        return "disabled"
    if source["id"] in blocked:
        return "blocked"
    return "due" if engine.is_due(record, now=now) else "waiting"


def due(*, rootdir: str = None) -> dict:
    """What the next tick would fetch, and when each other source is next due."""
    parts = components(rootdir)
    now = utcnow()
    rows, unreadable = [], []
    for watch_id, spec, error in _each_spec(parts["specs"]):
        if error:
            unreadable.append({"watch": watch_id, "error": error})
            continue
        state = parts["malls"](watch_id)["state"]
        blocked = blocked_source_ids(spec)
        for source in spec["sources"]:
            record = state.get(engine.state_key(source), {})
            rows.append(
                {
                    "watch": watch_id,
                    "source": source["id"],
                    "status": _source_status(spec, source, record, blocked, now),
                    "next_due": record.get("next_due"),
                    "last_run": record.get("last_run"),
                    "failures": record.get("failures", 0),
                    "last_error": record.get("last_error"),
                }
            )
    return {
        "ok": not unreadable,
        "due": sum(r["status"] == "due" for r in rows),
        "sources": rows,
        "unreadable": unreadable,
    }


def tick(*, watch: str = None, force: bool = False, rootdir: str = None) -> dict:
    """Run everything that is due: fetch, match, store, and write the digests that are due. Safe to run as often as you like; this is what the scheduler calls. `watch` limits it to comma-separated watch ids; `force` ignores the schedule."""
    parts = components(rootdir)
    return engine.tick(
        _csv(watch) or None, specs=parts["specs"], malls=parts["malls"], matcher=parts["matcher"], lock=parts["lock"](), force=force,
        on_digest_due=_digest.scheduled_digest(summarizer=parts["summarizer"], senders=parts["senders"]),
    )  # fmt: skip


def whats_new(
    watch_id: str,
    *,
    since: str = None,
    max_items: int = None,
    as_text: bool = False,
    rootdir: str = None,
) -> dict:
    """What a watch acquired since `since` (a time, or a duration ago such as 3d; default: since the last digest). Grouped by subtopic, best first. `as_text` adds the Markdown rendering."""
    _, spec = _load(watch_id, rootdir)
    data = _digest.whats_new(
        spec, components(rootdir)["malls"](watch_id), since=since, max_items=max_items
    )
    if as_text:
        data["text"] = components(rootdir)["summarizer"](data)
    return {"ok": True, **data}


def items(
    watch_id: str,
    *,
    query: str = None,
    subtopic: str = None,
    entity: str = None,
    source: str = None,
    since: str = None,
    limit: int = 20,
    rootdir: str = None,
) -> dict:
    """Search the stored items of a watch: words in the title or summary, a subtopic, an entity, a source, a time. Newest first."""
    _load(watch_id, rootdir)
    words = (query or "").lower().split()
    floor = to_datetime(since) if since else None

    def keep(item):
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        return (
            all(word in text for word in words)
            and (not subtopic or subtopic in item.get("subtopics", []))
            and (not entity or entity in item.get("entities", []))
            and (not source or source == item.get("source"))
            and (not floor or to_datetime(item["acquired"]) >= floor)
        )

    found = sorted(
        (
            i
            for i in components(rootdir)["malls"](watch_id)["items"].values()
            if keep(i)
        ),
        key=lambda i: i.get("published") or i["acquired"],
        reverse=True,
    )
    return {"ok": True, "count": len(found), "items": found[:limit]}


def entities(watch_id: str, *, rootdir: str = None) -> dict:
    """The tracked things of a watch, with how often and when each was last seen."""
    _, spec = _load(watch_id, rootdir)
    seen = dict(components(rootdir)["malls"](watch_id)["entities"].items())
    rows = [
        {
            **entity,
            **{
                k: v
                for k, v in seen.get(entity["id"], {}).items()
                if k != "observations"
            },
            "mentions": seen.get(entity["id"], {}).get("mentions", 0),
        }
        for entity in spec["entities"]
    ]
    return {"ok": True, "entities": sorted(rows, key=lambda e: -e["mentions"])}


def digest(
    watch_id: str,
    *,
    since: str = None,
    send: bool = False,
    mark_reported: bool = False,
    rootdir: str = None,
) -> dict:
    """Write a digest now and deliver it to the watch's channels. Without `send` it is a dry run that changes nothing: show the text and the channels to the user first, because a real send reaches people and cannot be unsent. `mark_reported` counts the items as reported without sending, for a digest that was only read here."""
    _, spec = _load(watch_id, rootdir)
    parts = components(rootdir)
    result = _digest.make_digest(
        spec, parts["malls"](watch_id), since=since, send=send, mark_reported=send or mark_reported,
        summarizer=parts["summarizer"], senders=parts["senders"],
    )  # fmt: skip
    return {"ok": all(d["ok"] for d in result["deliveries"]), "sent": send, **result}


def schedule(
    *, kind: str = None, every_minutes: int = DEFAULT_TICK_EVERY_MINUTES
) -> dict:
    """The scheduler entry that runs `keeptabs tick` regularly: a launchd property list (macOS), a cron line, or a systemd timer. It is returned, not installed; `install` says how."""
    import os
    import shlex
    from xml.sax.saxutils import escape

    kind = kind or ("launchd" if sys.platform == "darwin" else "cron")
    command = [sys.executable, "-m", "keeptabs", "tick"]
    if os.environ.get(
        ROOTDIR_ENV_VAR
    ):  # the scheduler does not inherit this shell's environment
        command += ["--rootdir", os.environ[ROOTDIR_ENV_VAR]]
    if every_minutes < 1:
        raise ValueError(
            f"The interval must be at least one minute, not {every_minutes}."
        )
    if kind == "cron":
        if every_minutes > 60 or 60 % every_minutes:
            raise ValueError(
                f"cron needs an interval that divides an hour (5, 10, 15, 20, 30, 60), not {every_minutes}."
            )
        minutes = "0" if every_minutes == 60 else f"*/{every_minutes}"
        text = f"{minutes} * * * * {shlex.join(command)} >/dev/null 2>&1"
        install = "Add the line with `crontab -e`."
    elif kind == "launchd":
        arguments = "\n".join(
            f"        <string>{escape(part)}</string>" for part in command
        )
        text = LAUNCHD_TEMPLATE.format(
            label=LAUNCHD_LABEL, arguments=arguments, seconds=every_minutes * 60
        )
        install = f"Save it as ~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist, then run: launchctl load ~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist"
    elif kind == "systemd":
        text = SYSTEMD_TEMPLATE.format(
            command=shlex.join(command), minutes=every_minutes
        )
        install = "Split it into ~/.config/systemd/user/keeptabs.service and keeptabs.timer, then run: systemctl --user enable --now keeptabs.timer"
    else:
        raise ValueError(f"Unknown scheduler {kind!r}. Known: launchd, cron, systemd.")
    return {
        "ok": True,
        "kind": kind,
        "every_minutes": every_minutes,
        "text": text,
        "install": install,
    }


#: The single list every surface is built from.
TOOLS = [
    examples,
    watches,
    watch,
    init_watch,
    edit_watch,
    add_source,
    remove_source,
    add_keywords,
    add_entity,
    add_action,
    resolve_action,
    pending,
    due,
    tick,
    whats_new,
    items,
    entities,
    digest,
    schedule,
]
