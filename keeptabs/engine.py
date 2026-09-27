"""The scheduled run: work out what is due, acquire it, match it, store it.

:func:`tick` is idempotent and safe to call as often as you like. Whether a source
is due is computed from stored state, so any trigger works (cron, launchd, a
systemd timer, a loop) and a missed run is simply caught up by the next one.
"""

from contextlib import contextmanager, nullcontext
from datetime import timedelta
from functools import partial

from keeptabs.fetchers import DEFAULT_FETCHERS, http_get as default_http_get
from keeptabs.matching import keyword_matcher
from keeptabs.spec import blocked_source_ids, normalize_spec
from keeptabs.stores import spec_store, watch_mall
from keeptabs.util import (
    app_dir,
    canonical_url,
    is_safe_id,
    isoformat,
    item_id,
    parse_duration,
    slug,
    timestamp_key,
    to_datetime,
    utcnow,
)

MAX_BACKOFF_FACTOR = 8
MAX_ENTITY_OBSERVATIONS = 200
LOCK_FILENAME = "tick.lock"
CANDIDATE_KIND = "candidate"


class AlreadyRunning(RuntimeError):
    """Another tick holds the lock."""


@contextmanager
def tick_lock(rootdir=None):
    """Hold the local lock that keeps two ticks from running at once.

    The operating system releases it when the process ends, however it ends.
    """
    from filelock import FileLock, Timeout

    path = app_dir(rootdir=rootdir) / LOCK_FILENAME
    lock = FileLock(str(path))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise AlreadyRunning(
            f"Another tick is running (it holds the lock {path.name}). Try again when it is done."
        ) from None
    try:
        yield
    finally:
        lock.release()


def is_due(state: dict, *, now) -> bool:
    """Whether a source (or a digest) with this stored state should run now.

    >>> now = to_datetime('2026-01-02')
    >>> is_due({}, now=now), is_due({'next_due': '2026-01-03T00:00:00+00:00'}, now=now)
    (True, False)
    """
    next_due = state.get("next_due")
    return next_due is None or to_datetime(next_due) <= now


def runnable_sources(spec: dict) -> list:
    """The sources of a spec that are enabled and wait on no human action."""
    blocked = blocked_source_ids(spec)
    return [
        source
        for source in spec["sources"]
        if source["enabled"] and source["id"] not in blocked
    ]


def due_sources(spec: dict, state_store, *, now=None) -> list:
    """The sources of a spec that should be fetched now."""
    now = now or utcnow()
    return [
        s
        for s in runnable_sources(spec)
        if is_due(state_store.get(state_key(s), {}), now=now)
    ]


def state_key(source) -> str:
    """The key of a source's record in the ``state`` store."""
    return f"source--{source['id']}"


def _item_key(raw: dict) -> str:
    url = raw.get("url") or ""
    return (
        canonical_url(url)
        if url.startswith("http")
        else (url or raw.get("guid") or raw.get("title", ""))
    )


def _observe_entities(entities_store, spec, item, *, now):
    known = {entity["id"]: entity for entity in spec["entities"]}
    for entity_id in item["entities"]:
        # a matcher may name a thing the spec does not list yet: keep it as a candidate
        seed = known.get(entity_id) or {
            "id": entity_id,
            "name": entity_id,
            "kind": CANDIDATE_KIND,
        }
        record = entities_store.get(entity_id) or {
            **seed,
            "first_seen": isoformat(now),
            "mentions": 0,
            "observations": [],
        }
        record["last_seen"] = isoformat(now)
        record["mentions"] += 1
        record["observations"] = (record["observations"] + [item["id"]])[
            -MAX_ENTITY_OBSERVATIONS:
        ]
        entities_store[entity_id] = record


def _store_new_items(raw_items, spec, source, mall, *, matcher, now, run):
    for raw in raw_items:
        run["fetched"] += 1
        key = _item_key(raw)
        if not key:
            continue
        identifier = item_id(key)
        if identifier in mall["items"] or identifier in mall["dropped"]:
            continue
        run["new"] += 1
        match = dict(matcher(raw, spec, mall=mall))
        match["entities"] = [
            e if is_safe_id(e) else slug(str(e)) for e in match.get("entities", [])
        ]
        item = {
            **raw,
            "id": identifier,
            "url": key if key.startswith("http") else raw.get("url"),
            "watch": spec["id"],
            "source": source["id"],
            "source_kind": source["kind"],
            "acquired": isoformat(now),
            **match,
        }
        if match.get("duplicate_of"):
            mall["dropped"][identifier] = {**item, "reason": "duplicate"}
        elif match.get("score", 0) < spec["min_score"] and not source["keep_all"]:
            mall["dropped"][identifier] = {**item, "reason": "below min_score"}
        else:
            mall["items"][identifier] = item
            _observe_entities(mall["entities"], spec, item, now=now)
            run["kept"] += 1


def fetch_source(spec, source, mall, *, fetchers, http_get, matcher, now) -> dict:
    """Fetch one source and store what is new. Returns the run record.

    It never raises for a failing source: the failure is recorded, the source
    backs off, and the caller carries on.
    """
    key = state_key(source)
    state = mall["state"].get(key, {})
    cadence = parse_duration(source["cadence"])
    run = {
        "watch": spec["id"],
        "source": source["id"],
        "at": isoformat(now),
        "fetched": 0,
        "new": 0,
        "kept": 0,
        "ok": True,
    }
    try:
        if source["kind"] not in fetchers:
            raise LookupError(
                f"No fetcher for source kind {source['kind']!r}. Known kinds: {', '.join(sorted(fetchers))}. "
                "Pass one to the run: tick(fetchers={kind: fetch})."
            )
        raw_items, cursor = fetchers[source["kind"]](
            source, state=state.get("cursor", {}), http_get=http_get
        )
        # the items first, the state after: a crash repeats work, never loses it
        _store_new_items(
            raw_items, spec, source, mall, matcher=matcher, now=now, run=run
        )
        state = {"cursor": cursor, "failures": 0, "last_ok": isoformat(now)}
        delay = cadence
    except Exception as error:  # one broken source must not stop the others
        failures = state.get("failures", 0) + 1
        state = {
            **state,
            "failures": failures,
            "last_error": f"{type(error).__name__}: {error}",
        }
        run.update(ok=False, error=state["last_error"])
        delay = cadence * min(2 ** (failures - 1), MAX_BACKOFF_FACTOR)
    state["last_run"] = isoformat(now)
    state["next_due"] = isoformat(now + timedelta(seconds=delay))
    mall["state"][key] = state
    mall["runs"][f"{timestamp_key(now)}--{source['id']}"] = run
    return run


def _run_watch(
    watch_id, specs, malls, *, fetchers, http_get, matcher, on_digest_due, now, force
):
    if watch_id not in specs:
        raise KeyError(
            f"No watch named {watch_id!r}. Known watches: {', '.join(sorted(specs)) or 'none yet'}."
        )
    spec = normalize_spec(specs[watch_id], watch_id=watch_id)
    if not spec["enabled"]:
        return [], None
    mall = malls(watch_id)
    sources = (
        runnable_sources(spec) if force else due_sources(spec, mall["state"], now=now)
    )
    runs = [
        fetch_source(
            spec,
            source,
            mall,
            fetchers=fetchers,
            http_get=http_get,
            matcher=matcher,
            now=now,
        )
        for source in sources
    ]
    digest = None
    if on_digest_due is not None:
        digest_state = mall["state"].get("digest", {})
        if "next_due" not in digest_state:
            # a new watch reports after one full period, on everything acquired since its first run
            period = parse_duration(spec["digest"]["cadence"])
            mall["state"]["digest"] = {
                "next_due": isoformat(now + timedelta(seconds=period)),
                "last_digest": isoformat(now - timedelta(seconds=1)),
            }
        elif is_due(digest_state, now=now):
            digest = on_digest_due(spec, mall, now)
    return runs, digest


def tick(
    watch_ids=None,
    *,
    rootdir=None,
    specs=None,
    malls=None,
    fetchers=None,
    http_get=None,
    matcher=None,
    on_digest_due=None,
    lock=None,
    now=None,
    force=False,
) -> dict:
    """Run everything that is due, once, and say what happened.

    - ``specs``: the store of watch specifications (default: local files under ``rootdir``).
    - ``malls``: a function from a watch id to that watch's stores (default: local files).
    - ``fetchers``: source kind to fetcher, added to the defaults.
    - ``http_get``: the one door to the network.
    - ``matcher``: ``match(item, spec, *, mall)``, scoring an item against a spec.
    - ``on_digest_due``: called with ``(spec, mall, now)`` for each watch whose digest is due.
    - ``lock``: a context manager held for the run (default: a local file lock);
      ``False`` for none, when your stores do their own locking.
    - ``force``: run every enabled, unblocked source whatever its schedule.

    A watch or a source that fails is reported in ``failures`` and does not stop the rest.
    """
    now = to_datetime(now) if now else utcnow()
    specs = spec_store(rootdir) if specs is None else specs
    malls = partial(watch_mall, rootdir=rootdir) if malls is None else malls
    fetchers = {**DEFAULT_FETCHERS, **(fetchers or {})}
    http_get = http_get or default_http_get
    matcher = matcher or keyword_matcher
    lock = (
        nullcontext()
        if lock is False
        else (tick_lock(rootdir) if lock is None else lock)
    )
    runs, digests, failures = [], [], []
    with lock:
        for watch_id in watch_ids or sorted(specs):
            try:
                watch_runs, digest = _run_watch(
                    watch_id, specs, malls, fetchers=fetchers, http_get=http_get,
                    matcher=matcher, on_digest_due=on_digest_due, now=now, force=force,
                )  # fmt: skip
            except Exception as error:  # one broken watch must not stop the others
                message = (
                    error.args[0]
                    if isinstance(error, KeyError) and error.args
                    else error
                )
                failures.append(
                    {
                        "watch": watch_id,
                        "source": None,
                        "ok": False,
                        "error": f"{type(error).__name__}: {message}",
                    }
                )
                continue
            runs.extend(watch_runs)
            if digest is not None:
                digests.append(digest)
    failures.extend(run for run in runs if not run["ok"])
    return {
        "ok": not failures,
        "at": isoformat(now),
        "sources_run": len(runs),
        "items_kept": sum(run["kept"] for run in runs),
        "failures": failures,
        "runs": runs,
        "digests": digests,
    }
