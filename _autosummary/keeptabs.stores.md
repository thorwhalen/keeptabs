# keeptabs.stores

Where specs and acquired data live, behind `MutableMapping` interfaces.

Layout under the root (`~/.local/share/keeptabs` by default, never a repository):

```default
specs/<watch_id>.yaml
data/<watch_id>/{items,dropped,entities,runs,digests,state}/<key>.json
```

To store elsewhere, pass your own mappings: [`keeptabs.engine.tick()`](keeptabs.engine.md#keeptabs.engine.tick) takes
`specs=` (a mapping of watch id to spec) and `malls=` (a function from a watch
id to that watch’s stores). The factories here are the local default.

### Module Attributes

| [`STORE_KINDS`](#keeptabs.stores.STORE_KINDS)   | what was seen and judged irrelevant, so it is not judged again.   |
|----------------------------------------------------------------|-------------------------------------------------------------------|

### Functions

| [`json_store`](#keeptabs.stores.json_store)(\*parts[, rootdir])      | A store of JSON records, keyed without the file extension.        |
|--------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| [`memory_mall`](#keeptabs.stores.memory_mall)()                       | The stores of one watch, in memory: for tests and throwaway runs. |
| [`spec_store`](#keeptabs.stores.spec_store)([rootdir])               | Watch specifications, keyed by watch id, stored as YAML files.    |
| [`watch_mall`](#keeptabs.stores.watch_mall)(watch_id, \*[, rootdir]) | The stores of one watch.                                          |

### keeptabs.stores.STORE_KINDS *= ('items', 'dropped', 'entities', 'runs', 'digests', 'state')*

what was seen and judged irrelevant, so it is not
judged again. entities: what is known about each tracked thing. runs: what each
fetch did. digests: what was written and sent. state: cursors and due times.

* **Type:**
  items
* **Type:**
  what was kept. dropped

### keeptabs.stores.json_store(\*parts, rootdir=None)

A store of JSON records, keyed without the file extension.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

### keeptabs.stores.memory_mall()

The stores of one watch, in memory: for tests and throwaway runs.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> sorted(memory_mall()) == sorted(STORE_KINDS)
True
```

### keeptabs.stores.spec_store(rootdir=None)

Watch specifications, keyed by watch id, stored as YAML files.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

### keeptabs.stores.watch_mall(watch_id, , rootdir=None)

The stores of one watch.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> import tempfile
>>> mall = watch_mall('demo', rootdir=tempfile.mkdtemp())
>>> sorted(mall)
['digests', 'dropped', 'entities', 'items', 'runs', 'state']
>>> mall['items']['abc'] = {'title': 'Ça marche'}
>>> mall['items']['abc'], list(mall['items'])
({'title': 'Ça marche'}, ['abc'])
```
