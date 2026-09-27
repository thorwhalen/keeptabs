# keeptabs.engine

The scheduled run: work out what is due, acquire it, match it, store it.

[`tick()`](#keeptabs.engine.tick) is idempotent and safe to call as often as you like. Whether a source
is due is computed from stored state, so any trigger works (cron, launchd, a
systemd timer, a loop) and a missed run is simply caught up by the next one.

### Functions

| [`due_sources`](#keeptabs.engine.due_sources)(spec, state_store, \*[, now])     | The sources of a spec that should be fetched now.                     |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`fetch_source`](#keeptabs.engine.fetch_source)(spec, source, mall, \*, ...)     | Fetch one source and store what is new.                               |
| [`is_due`](#keeptabs.engine.is_due)(state, \*, now)                        | Whether a source (or a digest) with this stored state should run now. |
| [`runnable_sources`](#keeptabs.engine.runnable_sources)(spec)                        | The sources of a spec that are enabled and wait on no human action.   |
| [`state_key`](#keeptabs.engine.state_key)(source)                             | The key of a source's record in the `state` store.                    |
| [`tick`](#keeptabs.engine.tick)([watch_ids, rootdir, specs, malls, ...]) | Run everything that is due, once, and say what happened.              |
| [`tick_lock`](#keeptabs.engine.tick_lock)([rootdir])                          | Hold the local lock that keeps two ticks from running at once.        |

### Exceptions

| [`AlreadyRunning`](#keeptabs.engine.AlreadyRunning)   | Another tick holds the lock.   |
|-------------------------------------------------------------------|--------------------------------|

### *exception* keeptabs.engine.AlreadyRunning

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Another tick holds the lock.

### keeptabs.engine.due_sources(spec, state_store, , now=None)

The sources of a spec that should be fetched now.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### keeptabs.engine.fetch_source(spec, source, mall, , fetchers, http_get, matcher, now)

Fetch one source and store what is new. Returns the run record.

It never raises for a failing source: the failure is recorded, the source
backs off, and the caller carries on.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.engine.is_due(state, , now)

Whether a source (or a digest) with this stored state should run now.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> now = to_datetime('2026-01-02')
>>> is_due({}, now=now), is_due({'next_due': '2026-01-03T00:00:00+00:00'}, now=now)
(True, False)
```

### keeptabs.engine.runnable_sources(spec)

The sources of a spec that are enabled and wait on no human action.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### keeptabs.engine.state_key(source)

The key of a source’s record in the `state` store.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.engine.tick(watch_ids=None, , rootdir=None, specs=None, malls=None, fetchers=None, http_get=None, matcher=None, on_digest_due=None, lock=None, now=None, force=False)

Run everything that is due, once, and say what happened.

- `specs`: the store of watch specifications (default: local files under `rootdir`).
- `malls`: a function from a watch id to that watch’s stores (default: local files).
  Stores of your own come in a pair: give both `specs` and `malls`.
- `fetchers`: source kind to fetcher, added to the defaults.
- `http_get`: the one door to the network.
- `matcher`: `match(item, spec, *, mall)`, scoring an item against a spec.
- `on_digest_due`: called with `(spec, mall, now)` for each watch whose digest is
  due (default: [`keeptabs.digest.scheduled_digest()`](keeptabs.digest.md#keeptabs.digest.scheduled_digest)); `False` for no digest.
- `lock`: a context manager held for the run, or `False` for none. The default
  is a local file lock, and none when the stores are your own.
- `force`: run every enabled, unblocked source whatever its schedule.

A watch or a source that fails is reported in `failures` and does not stop the rest.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### keeptabs.engine.tick_lock(rootdir=None)

Hold the local lock that keeps two ticks from running at once.

The operating system releases it when the process ends, however it ends.
