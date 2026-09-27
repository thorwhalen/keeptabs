"""The watch specification: what one tracked area is, and how it is watched.

A spec is a plain ``dict`` on disk (YAML) so an agent can read and write it without
this package. :func:`normalize_spec` is the single place that fills defaults and
rejects what cannot work, so every other module may assume a complete spec.
"""

import math
from collections.abc import Mapping
from copy import deepcopy

from keeptabs.util import is_safe_id, item_id, parse_duration, slug

# The kinds that have a fetcher out of the box. A spec may use any other kind, as
# long as a fetcher for it is passed to the run (``tick(fetchers={kind: fetch})``).
SOURCE_KINDS = (
    "feed",
    "arxiv",
    "github_releases",
    "hackernews",
    "news_search",
    "email",
)

# What identifies the thing to fetch, per source kind. Other kinds use ``target``.
DEFAULT_TARGET_FIELD = "target"
SOURCE_TARGET_FIELD = {
    "feed": "url",
    "arxiv": "query",
    "github_releases": "repo",
    "hackernews": "query",
    "news_search": "query",
    "email": "sender",
}

DEFAULT_SOURCE_CADENCE = "1d"
DEFAULT_DIGEST_CADENCE = "1w"
DEFAULT_MIN_SCORE = 1.0
DEFAULT_MAX_ITEMS_PER_FETCH = 50
DEFAULT_MAX_ITEMS_PER_DIGEST = 30
AUTO_ID_SLUG_CHARS = 60
PRIORITIES = ("high", "medium", "low")
ACTION_STATUSES = ("open", "done", "dropped")

_TRUE, _FALSE = ("true", "yes", "on", "1"), ("false", "no", "off", "0")


class SpecError(ValueError):
    """A watch specification that cannot be used, with the reason and the fix."""


def target_field(kind: str) -> str:
    """The field of a source that says what to fetch.

    >>> target_field('feed'), target_field('github_releases'), target_field('my_own_kind')
    ('url', 'repo', 'target')
    """
    return SOURCE_TARGET_FIELD.get(kind, DEFAULT_TARGET_FIELD)


def str_list(value, *, what="value") -> list:
    """A list of strings from what a hand-written spec may hold.

    A bare string is one term, not a list of characters.

    >>> str_list('diffusion'), str_list(['LLM', 2026]), str_list(None)
    (['diffusion'], ['LLM', '2026'], [])

    YAML reads an unquoted ``NO`` as false and ``3.10`` as 3.1. What was written
    cannot be recovered, so such a term is refused, with the fix:

    >>> str_list(['LLM', False], what='keywords')
    Traceback (most recent call last):
      ...
    keeptabs.spec.SpecError: keywords holds False, which is not text. Put the term in quotes, as in "no" or "3.10".
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping) or not hasattr(value, "__iter__"):
        raise SpecError(f"{what} must be a list of terms, not {value!r}.")
    terms = []
    for term in value:
        if (
            isinstance(term, (bool, float))
            or term is None
            or not isinstance(term, (str, int))
        ):
            raise SpecError(
                f'{what} holds {term!r}, which is not text. Put the term in quotes, as in "no" or "3.10".'
            )
        if str(term).strip():
            terms.append(str(term))
    return terms


def as_bool(value, *, what) -> bool:
    """A yes or no, from a boolean or from the words for one.

    >>> as_bool('false', what='enabled'), as_bool(True, what='enabled')
    (False, True)
    """
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in _TRUE or word in _FALSE:
        return word in _TRUE
    raise SpecError(f"{what} must be true or false, not {value!r}.")


def _as_number(value, *, what, kind=float, minimum=None):
    try:
        number = kind(value)
    except (TypeError, ValueError):
        raise SpecError(f"{what} must be a number, not {value!r}.") from None
    if isinstance(value, bool) or math.isnan(number) or math.isinf(number):
        raise SpecError(f"{what} must be a number, not {value!r}.")
    if minimum is not None and number < minimum:
        raise SpecError(f"{what} must be at least {minimum}, not {value!r}.")
    return number


def _as_duration(value, *, what):
    try:
        parse_duration(value)
    except ValueError as error:
        raise SpecError(f"{what}: {error}") from None
    return value


def _records(value, what, *, from_text) -> list:
    """The records of a list field, each a dict. A bare string is read with ``from_text``."""
    if value is None:
        return []
    if isinstance(value, (str, Mapping)) or not hasattr(value, "__iter__"):
        raise SpecError(f"{what} must be a list, not {value!r}.")
    records = []
    for record in value:
        if isinstance(record, str):
            record = from_text(record)
        if not isinstance(record, Mapping):
            raise SpecError(
                f"Each of the {what} must be a mapping of fields, not {record!r}."
            )
        records.append(dict(record))
    return records


def _checked_id(identifier, what):
    if not is_safe_id(identifier):
        raise SpecError(
            f"The id {str(identifier)[:80]!r} of a {what} cannot be used: ids become file names, so they are "
            f"lowercase letters, digits, '-', '_' and '.', at most 100 characters. Try {slug(str(identifier))[:80]!r}."
        )
    return str(identifier)


def _source_id(source: dict) -> str:
    target = str(source.get(target_field(source["kind"]), ""))
    # the hash keeps two targets apart when their slugs are the same, or are cut short
    return f"{slug(source['kind'] + '-' + target)[:AUTO_ID_SLUG_CHARS].strip('-')}-{item_id(target)[:6]}"


def _source_from_text(text):
    if text.startswith(("http://", "https://")):
        return {"kind": "feed", "url": text}
    raise SpecError(
        f"A source is a mapping with a 'kind', or the URL of a feed, not {text!r}."
    )


def normalize_source(source: dict) -> dict:
    """One source with defaults filled in and its fields checked.

    >>> s = normalize_source({'kind': 'feed', 'url': 'https://example.com/feed.xml'})
    >>> s['id'], s['cadence'], s['enabled'], s['keep_all']
    ('feed-https-example-com-feed-xml-7a775d', '1d', True, False)

    A kind with no fetcher of its own is accepted, and says what to fetch in ``target``:

    >>> normalize_source({'kind': 'my_api', 'target': 'robots', 'id': 'robots'})['id']
    'robots'
    """
    if not isinstance(source, Mapping):
        raise SpecError(f"A source must be a mapping of fields, not {source!r}.")
    source = dict(source)
    kind = source.get("kind")
    if not kind or not isinstance(kind, str):
        raise SpecError(f"A source needs a 'kind', such as {', '.join(SOURCE_KINDS)}.")
    field = target_field(kind)
    if not source.get(field) and kind != "email" and not source.get("id"):
        raise SpecError(f"A {kind!r} source needs a {field!r} field.")
    source["id"] = _checked_id(source.get("id") or _source_id(source), "source")
    source.setdefault("title", str(source.get(field) or source["id"]))
    source["cadence"] = _as_duration(
        source.get("cadence", DEFAULT_SOURCE_CADENCE), what=f"cadence of {source['id']}"
    )
    source["enabled"] = as_bool(
        source.get("enabled", True), what=f"enabled of {source['id']}"
    )
    # keep_all: a source curated for this very topic, whose items need no keyword match
    source["keep_all"] = as_bool(
        source.get("keep_all", False), what=f"keep_all of {source['id']}"
    )
    source["max_items"] = _as_number(
        source.get("max_items", DEFAULT_MAX_ITEMS_PER_FETCH),
        what=f"max_items of {source['id']}",
        kind=int,
        minimum=1,
    )
    return source


def _normalize_subtopic(subtopic: dict) -> dict:
    if not subtopic.get("id"):
        if not subtopic.get("title"):
            raise SpecError("A subtopic needs an 'id' or a 'title'.")
        subtopic["id"] = slug(str(subtopic["title"]))
    subtopic["id"] = _checked_id(subtopic["id"], "subtopic")
    subtopic.setdefault("title", subtopic["id"])
    subtopic.setdefault("priority", "medium")
    if subtopic["priority"] not in PRIORITIES:
        raise SpecError(
            f"Subtopic priority must be one of {PRIORITIES}, not {subtopic['priority']!r}."
        )
    subtopic["keywords"] = str_list(
        subtopic.get("keywords"), what=f"keywords of {subtopic['id']}"
    )
    return subtopic


def _normalize_entity(entity: dict) -> dict:
    if not entity.get("name"):
        raise SpecError("An entity needs a 'name'.")
    entity["name"] = str(entity["name"])
    entity["id"] = _checked_id(entity.get("id") or slug(entity["name"]), "entity")
    entity.setdefault("kind", "thing")
    entity["aliases"] = str_list(
        entity.get("aliases"), what=f"aliases of {entity['id']}"
    )
    return entity


def _normalize_action(action: dict) -> dict:
    if not action.get("action"):
        raise SpecError(
            "A pending action needs an 'action' field saying what the human must do."
        )
    action["id"] = _checked_id(
        action.get("id") or slug(str(action["action"]))[:60].strip("-"),
        "pending action",
    )
    action["blocks"] = str_list(action.get("blocks"), what=f"blocks of {action['id']}")
    action.setdefault("status", "open")
    if action["status"] not in ACTION_STATUSES:
        raise SpecError(
            f"Action status must be one of {ACTION_STATUSES}, not {action['status']!r}."
        )
    return action


def _normalize_digest(digest) -> dict:
    if isinstance(digest, str):
        digest = {"cadence": digest}
    if not isinstance(digest or {}, Mapping):
        raise SpecError(
            f"digest must be a mapping with cadence, channels and auto_send, not {digest!r}."
        )
    digest = dict(digest or {})
    digest["cadence"] = _as_duration(
        digest.get("cadence", DEFAULT_DIGEST_CADENCE), what="digest.cadence"
    )
    digest["channels"] = str_list(digest.get("channels"), what="digest.channels")
    # Nothing leaves the machine from the scheduled run unless the owner said so.
    digest["auto_send"] = as_bool(
        digest.get("auto_send", False), what="digest.auto_send"
    )
    digest["max_items"] = _as_number(
        digest.get("max_items", DEFAULT_MAX_ITEMS_PER_DIGEST),
        what="digest.max_items",
        kind=int,
        minimum=1,
    )
    return digest


def _unique(records, what):
    seen = set()
    for record in records:
        if record["id"] in seen:
            raise SpecError(
                f"Two {what} share the id {record['id']!r}. Give one of them an explicit 'id'."
            )
        seen.add(record["id"])
    return records


def normalize_spec(spec: dict, *, watch_id=None) -> dict:
    """A complete, checked copy of a watch specification.

    Only ``id`` (or ``title``) is required: a spec starts as a vague idea.

    >>> spec = normalize_spec({'title': 'Gen AI', 'keywords': ['diffusion'], 'entities': ['Sora']})
    >>> spec['id'], spec['min_score'], spec['digest']['cadence'], spec['sources']
    ('gen-ai', 1.0, '1w', [])
    >>> spec['entities']
    [{'name': 'Sora', 'id': 'sora', 'kind': 'thing', 'aliases': []}]
    """
    if not isinstance(spec, Mapping):
        raise SpecError(
            f"A watch specification is a mapping of fields, not {type(spec).__name__}."
        )
    spec = deepcopy(dict(spec))
    spec_id = watch_id or spec.get("id") or slug(str(spec.get("title", "")))
    if not spec_id:
        raise SpecError("A watch needs an 'id' or a 'title'.")
    if spec_id != slug(str(spec_id)) or not is_safe_id(spec_id):
        raise SpecError(
            f"Watch id {str(spec_id)[:80]!r} must be kebab-case, e.g. {slug(str(spec_id))[:80]!r}."
        )
    spec["id"] = spec_id
    spec["title"] = str(spec.get("title") or spec_id)
    spec.setdefault("intent", "")
    spec.setdefault("scope", "")
    spec["enabled"] = as_bool(spec.get("enabled", True), what="enabled")
    spec["min_score"] = _as_number(
        spec.get("min_score", DEFAULT_MIN_SCORE), what="min_score"
    )
    spec["keywords"] = str_list(spec.get("keywords"), what="keywords")
    spec["exclude_keywords"] = str_list(
        spec.get("exclude_keywords"), what="exclude_keywords"
    )
    subtopics = _records(
        spec.get("subtopics"), "subtopics", from_text=lambda text: {"title": text}
    )
    entities = _records(
        spec.get("entities"), "entities", from_text=lambda text: {"name": text}
    )
    sources = _records(spec.get("sources"), "sources", from_text=_source_from_text)
    actions = _records(
        spec.get("pending_actions"),
        "pending actions",
        from_text=lambda text: {"action": text},
    )
    spec["subtopics"] = _unique(
        [_normalize_subtopic(s) for s in subtopics], "subtopics"
    )
    spec["entities"] = _unique([_normalize_entity(e) for e in entities], "entities")
    spec["sources"] = _unique([normalize_source(s) for s in sources], "sources")
    spec["digest"] = _normalize_digest(spec.get("digest"))
    spec["pending_actions"] = _unique(
        [_normalize_action(a) for a in actions], "pending actions"
    )
    return spec


def blocked_source_ids(spec: dict) -> set:
    """Sources that wait on a human action that is still open.

    >>> spec = normalize_spec({'id': 'w', 'sources': [{'kind': 'email', 'sender': 'a@b.c', 'id': 'nl'}],
    ...     'pending_actions': [{'action': 'Subscribe', 'blocks': ['nl']}]})
    >>> blocked_source_ids(spec)
    {'nl'}
    """
    return {
        source_id
        for action in spec.get("pending_actions", [])
        if action.get("status", "open") == "open"
        for source_id in action.get("blocks") or []
    }
