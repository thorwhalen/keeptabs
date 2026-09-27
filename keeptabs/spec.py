"""The watch specification: what one tracked area is, and how it is watched.

A spec is a plain ``dict`` on disk (YAML) so an agent can read and write it without
this package. :func:`normalize_spec` is the single place that fills defaults and
rejects what cannot work, so every other module may assume a complete spec.
"""

from copy import deepcopy

from keeptabs.util import is_safe_id, parse_duration, slug

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
PRIORITIES = ("high", "medium", "low")
ACTION_STATUSES = ("open", "done", "dropped")


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

    A bare string is one term, not a list of characters, and YAML's own readings
    of ``NO`` or ``3.11`` are turned back into text.

    >>> str_list('diffusion'), str_list(['LLM', 3.11, False]), str_list(None)
    (['diffusion'], ['LLM', '3.11', 'False'], [])
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict) or not hasattr(value, "__iter__"):
        raise SpecError(f"{what} must be a list of terms, not {value!r}.")
    return [str(term) for term in value if str(term).strip()]


def _checked_id(identifier, what):
    if not is_safe_id(identifier):
        raise SpecError(
            f"The id {identifier!r} of a {what} cannot be used: ids become file names, so they may "
            f"hold letters, digits, '-', '_' and '.' only. Try {slug(str(identifier))!r}."
        )
    return str(identifier)


def _source_id(source: dict) -> str:
    target = source.get(target_field(source.get("kind")), "")
    return slug(f"{source.get('kind', '')}-{target}")[:80]


def normalize_source(source: dict) -> dict:
    """One source with defaults filled in and its fields checked.

    >>> s = normalize_source({'kind': 'feed', 'url': 'https://example.com/feed.xml'})
    >>> s['id'], s['cadence'], s['enabled'], s['keep_all']
    ('feed-https-example-com-feed-xml', '1d', True, False)

    A kind with no fetcher of its own is accepted, and says what to fetch in ``target``:

    >>> normalize_source({'kind': 'my_api', 'target': 'robots'})['id']
    'my-api-robots'
    """
    source = dict(source)
    kind = source.get("kind")
    if not kind or not isinstance(kind, str):
        raise SpecError(f"A source needs a 'kind', such as {', '.join(SOURCE_KINDS)}.")
    field = target_field(kind)
    if not source.get(field) and kind != "email" and not source.get("id"):
        raise SpecError(f"A {kind!r} source needs a {field!r} field.")
    source["id"] = _checked_id(source.get("id") or _source_id(source), "source")
    source.setdefault("title", str(source.get(field) or source["id"]))
    source.setdefault("cadence", DEFAULT_SOURCE_CADENCE)
    parse_duration(source["cadence"])
    source["enabled"] = bool(source.get("enabled", True))
    # keep_all: a source curated for this very topic, whose items need no keyword match
    source["keep_all"] = bool(source.get("keep_all", False))
    source["max_items"] = int(source.get("max_items", DEFAULT_MAX_ITEMS_PER_FETCH))
    return source


def _normalize_subtopic(subtopic: dict) -> dict:
    subtopic = dict(subtopic)
    if not subtopic.get("id"):
        if not subtopic.get("title"):
            raise SpecError("A subtopic needs an 'id' or a 'title'.")
        subtopic["id"] = slug(subtopic["title"])
    subtopic["id"] = _checked_id(subtopic["id"], "subtopic")
    subtopic.setdefault("title", subtopic["id"])
    subtopic.setdefault("priority", "medium")
    if subtopic["priority"] not in PRIORITIES:
        raise SpecError(
            f"Subtopic priority must be one of {PRIORITIES}, not {subtopic['priority']!r}."
        )
    subtopic["keywords"] = str_list(
        subtopic.get("keywords"), what="A subtopic's keywords"
    )
    return subtopic


def _normalize_entity(entity: dict) -> dict:
    entity = dict(entity)
    if not entity.get("name"):
        raise SpecError("An entity needs a 'name'.")
    entity["name"] = str(entity["name"])
    entity["id"] = _checked_id(entity.get("id") or slug(entity["name"]), "entity")
    entity.setdefault("kind", "thing")
    entity["aliases"] = str_list(entity.get("aliases"), what="An entity's aliases")
    return entity


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

    >>> spec = normalize_spec({'title': 'Gen AI', 'keywords': ['diffusion']})
    >>> spec['id'], spec['min_score'], spec['digest']['cadence'], spec['sources']
    ('gen-ai', 1.0, '1w', [])
    """
    spec = deepcopy(dict(spec))
    spec_id = watch_id or spec.get("id") or slug(spec.get("title", ""))
    if not spec_id:
        raise SpecError("A watch needs an 'id' or a 'title'.")
    if spec_id != slug(spec_id):
        raise SpecError(
            f"Watch id {spec_id!r} must be kebab-case, e.g. {slug(spec_id)!r}."
        )
    spec["id"] = spec_id
    spec.setdefault("title", spec_id)
    spec.setdefault("intent", "")
    spec.setdefault("scope", "")
    spec.setdefault("enabled", True)
    try:
        spec["min_score"] = float(spec.get("min_score", DEFAULT_MIN_SCORE))
    except (TypeError, ValueError):
        raise SpecError(
            f"min_score must be a number, not {spec.get('min_score')!r}."
        ) from None
    spec["keywords"] = str_list(spec.get("keywords"), what="keywords")
    spec["exclude_keywords"] = str_list(
        spec.get("exclude_keywords"), what="exclude_keywords"
    )
    spec["subtopics"] = _unique(
        [_normalize_subtopic(s) for s in spec.get("subtopics") or []], "subtopics"
    )
    spec["entities"] = _unique(
        [_normalize_entity(e) for e in spec.get("entities") or []], "entities"
    )
    spec["sources"] = _unique(
        [normalize_source(s) for s in spec.get("sources") or []], "sources"
    )
    digest = dict(spec.get("digest") or {})
    digest.setdefault("cadence", DEFAULT_DIGEST_CADENCE)
    parse_duration(digest["cadence"])
    digest["channels"] = str_list(digest.get("channels"), what="digest.channels")
    # Nothing leaves the machine from the scheduled run unless the owner said so.
    digest["auto_send"] = digest.get("auto_send", False) is True
    digest["max_items"] = int(digest.get("max_items", 30))
    spec["digest"] = digest
    actions = []
    for action in spec.get("pending_actions") or []:
        action = dict(action)
        if not action.get("action"):
            raise SpecError(
                "A pending action needs an 'action' field saying what the human must do."
            )
        action["id"] = _checked_id(
            action.get("id") or slug(action["action"])[:60], "pending action"
        )
        action["blocks"] = str_list(action.get("blocks"), what="An action's blocks")
        action.setdefault("status", "open")
        if action["status"] not in ACTION_STATUSES:
            raise SpecError(
                f"Action status must be one of {ACTION_STATUSES}, not {action['status']!r}."
            )
        actions.append(action)
    spec["pending_actions"] = _unique(actions, "pending actions")
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
