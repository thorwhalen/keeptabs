"""Where specs and acquired data live, behind ``MutableMapping`` interfaces.

Layout under the root (``~/.local/share/keeptabs`` by default, never a repository)::

    specs/<watch_id>.yaml
    data/<watch_id>/{items,dropped,entities,runs,digests,state}/<key>.json

To store elsewhere, pass your own mappings: :func:`keeptabs.engine.tick` takes
``specs=`` (a mapping of watch id to spec) and ``malls=`` (a function from a watch
id to that watch's stores). The factories here are the local default.
"""

import json
from collections.abc import MutableMapping

import yaml
from dol import Files, KeyCodecs, wrap_kvs

from keeptabs.util import app_dir

#: items: what was kept. dropped: what was seen and judged irrelevant, so it is not
#: judged again. entities: what is known about each tracked thing. runs: what each
#: fetch did. digests: what was written and sent. state: cursors and due times.
STORE_KINDS = ("items", "dropped", "entities", "runs", "digests", "state")

ENCODING = "utf-8"  # never the platform default: specs and items hold any language


def _yaml_dumps(obj) -> bytes:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=10**6).encode(
        ENCODING
    )


def _json_dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=1).encode(ENCODING)


def spec_store(rootdir=None) -> MutableMapping:
    """Watch specifications, keyed by watch id, stored as YAML files."""
    files = Files(str(app_dir("specs", rootdir=rootdir)))
    as_yaml = wrap_kvs(
        files,
        obj_of_data=lambda data: yaml.safe_load(data.decode(ENCODING)),
        data_of_obj=_yaml_dumps,
    )
    return KeyCodecs.suffixed(".yaml")(as_yaml)


def json_store(*parts, rootdir=None) -> MutableMapping:
    """A store of JSON records, keyed without the file extension."""
    files = Files(str(app_dir(*parts, rootdir=rootdir)))
    as_json = wrap_kvs(
        files,
        obj_of_data=lambda data: json.loads(data.decode(ENCODING)),
        data_of_obj=_json_dumps,
    )
    return KeyCodecs.suffixed(".json")(as_json)


def watch_mall(watch_id: str, *, rootdir=None) -> dict:
    """The stores of one watch.

    >>> import tempfile
    >>> mall = watch_mall('demo', rootdir=tempfile.mkdtemp())
    >>> sorted(mall)
    ['digests', 'dropped', 'entities', 'items', 'runs', 'state']
    >>> mall['items']['abc'] = {'title': 'Ça marche'}
    >>> mall['items']['abc'], list(mall['items'])
    ({'title': 'Ça marche'}, ['abc'])
    """
    return {
        kind: json_store("data", watch_id, kind, rootdir=rootdir)
        for kind in STORE_KINDS
    }


def memory_mall() -> dict:
    """The stores of one watch, in memory: for tests and throwaway runs.

    >>> sorted(memory_mall()) == sorted(STORE_KINDS)
    True
    """
    return {kind: {} for kind in STORE_KINDS}
