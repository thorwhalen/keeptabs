# keeptabs.util

Small pure helpers: app directories, durations, timestamps, URL canonicalisation.

### Functions

| [`app_dir`](#keeptabs.util.app_dir)(\*parts[, rootdir])   | A directory under the root, created if missing.                              |
|--------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`canonical_url`](#keeptabs.util.canonical_url)(url)            | The same document should have the same URL, however it was linked.           |
| [`is_safe_id`](#keeptabs.util.is_safe_id)(identifier)        | Whether an identifier can be used as a store key (it becomes a file name).   |
| [`isoformat`](#keeptabs.util.isoformat)(when)               | The ISO 8601 form used in every stored record.                               |
| [`item_id`](#keeptabs.util.item_id)(key)                  | A short, filesystem-safe, stable identifier for an item key.                 |
| [`parse_duration`](#keeptabs.util.parse_duration)(duration)      | Seconds in a duration such as `'30m'`, `'6h'`, `'1d'` or `'2w'`.             |
| [`rootdir`](#keeptabs.util.rootdir)([rootdir])            | The directory that holds every spec and every watch's data.                  |
| [`slug`](#keeptabs.util.slug)(text)                    | A kebab-case identifier.                                                     |
| [`timestamp_key`](#keeptabs.util.timestamp_key)(when)           | A sortable store key for a moment, in UTC.                                   |
| [`to_datetime`](#keeptabs.util.to_datetime)(when, \*[, now])  | A timezone-aware datetime from a datetime, an ISO string, or a duration ago. |
| [`utcnow`](#keeptabs.util.utcnow)()                      | The current time, timezone-aware, in UTC.                                    |

### keeptabs.util.app_dir(\*parts, rootdir=None)

A directory under the root, created if missing.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### keeptabs.util.canonical_url(url)

The same document should have the same URL, however it was linked.

Lower-cases the scheme and host, drops the fragment, a trailing slash,
default ports and click-tracking parameters, and sorts what is left.

```pycon
>>> canonical_url('HTTPS://Example.com:443/a/?utm_source=x&b=2&a=1#top')
'https://example.com/a?a=1&b=2'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.util.is_safe_id(identifier)

Whether an identifier can be used as a store key (it becomes a file name).

Lowercase only, because some file systems do not tell `Feed` from `feed`.

```pycon
>>> [is_safe_id(i) for i in ('llama.cpp', 'gen-ai', '../../etc', 'a/b', '', 'Feed', 'con', 'abc.', 'x' * 101)]
[True, True, False, False, False, False, False, False, False]
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### keeptabs.util.isoformat(when)

The ISO 8601 form used in every stored record.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.util.item_id(key)

A short, filesystem-safe, stable identifier for an item key.

```pycon
>>> item_id('https://example.com/a')
'2dce0a4c50441bfc'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.util.parse_duration(duration)

Seconds in a duration such as `'30m'`, `'6h'`, `'1d'` or `'2w'`.

```pycon
>>> parse_duration('6h')
21600.0
>>> parse_duration(90)
90.0
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### keeptabs.util.rootdir(rootdir=None)

The directory that holds every spec and every watch’s data.

Resolution order: the argument, the `KEEPTABS_ROOTDIR` environment variable,
`$XDG_DATA_HOME/keeptabs`, then `~/.local/share/keeptabs`.

```pycon
>>> rootdir('/tmp/somewhere').name
'somewhere'
```

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### keeptabs.util.slug(text)

A kebab-case identifier.

```pycon
>>> slug('Music AI (real-time)')
'music-ai-real-time'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.util.timestamp_key(when)

A sortable store key for a moment, in UTC.

```pycon
>>> timestamp_key('2026-01-02T03:04:05+01:00')
'20260102t020405z'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### keeptabs.util.to_datetime(when, , now=None)

A timezone-aware datetime from a datetime, an ISO string, or a duration ago.

```pycon
>>> to_datetime('2026-01-02T03:04:05+00:00').isoformat()
'2026-01-02T03:04:05+00:00'
>>> base = to_datetime('2026-01-08')
>>> to_datetime('7d', now=base).isoformat()
'2026-01-01T00:00:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### keeptabs.util.utcnow()

The current time, timezone-aware, in UTC.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)
