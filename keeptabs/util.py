"""Small pure helpers: app directories, durations, timestamps, URL canonicalisation."""

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

APP_NAME = "keeptabs"
ROOTDIR_ENV_VAR = "KEEPTABS_ROOTDIR"

# Query parameters that identify a click, not a document.
TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "pk_", "hsa_", "vero_")
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "ref_src",
        "ref_url",
        "_hsenc",
        "_hsmi",
        "oly_anon_id",
        "oly_enc_id",
        "s_cid",
    }
)

_DURATION_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([mhdw])\s*$", re.IGNORECASE)


def rootdir(rootdir=None) -> Path:
    """The directory that holds every spec and every watch's data.

    Resolution order: the argument, the ``KEEPTABS_ROOTDIR`` environment variable,
    ``$XDG_DATA_HOME/keeptabs``, then ``~/.local/share/keeptabs``.

    >>> rootdir('/tmp/somewhere').name
    'somewhere'
    """
    if rootdir is not None:
        return Path(rootdir).expanduser()
    if os.environ.get(ROOTDIR_ENV_VAR):
        return Path(os.environ[ROOTDIR_ENV_VAR]).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(data_home).expanduser() / APP_NAME


def app_dir(*parts, rootdir=None) -> Path:
    """A directory under the root, created if missing."""
    path = globals()["rootdir"](rootdir).joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_duration(duration) -> float:
    """Seconds in a duration such as ``'30m'``, ``'6h'``, ``'1d'`` or ``'2w'``.

    >>> parse_duration('6h')
    21600.0
    >>> parse_duration(90)
    90.0
    """
    if isinstance(duration, (int, float)):
        return float(duration)
    match = _DURATION_RE.match(str(duration))
    if not match:
        raise ValueError(
            f"Not a duration: {duration!r}. Use a number of seconds, or a number followed by m, h, d or w (e.g. '6h')."
        )
    return float(match.group(1)) * _DURATION_UNITS[match.group(2).lower()]


def utcnow() -> datetime:
    """The current time, timezone-aware, in UTC."""
    return datetime.now(timezone.utc)


def to_datetime(when, *, now=None) -> datetime:
    """A timezone-aware datetime from a datetime, an ISO string, or a duration ago.

    >>> to_datetime('2026-01-02T03:04:05+00:00').isoformat()
    '2026-01-02T03:04:05+00:00'
    >>> base = to_datetime('2026-01-08')
    >>> to_datetime('7d', now=base).isoformat()
    '2026-01-01T00:00:00+00:00'
    """
    if isinstance(when, datetime):
        result = when
    elif _DURATION_RE.match(str(when)):
        result = (now or utcnow()) - timedelta(seconds=parse_duration(when))
    else:
        result = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    if result.tzinfo is None:  # a time with no zone is read as UTC
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def isoformat(when) -> str:
    """The ISO 8601 form used in every stored record."""
    return to_datetime(when).astimezone(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url: str) -> str:
    """The same document should have the same URL, however it was linked.

    Lower-cases the scheme and host, drops the fragment, a trailing slash,
    default ports and click-tracking parameters, and sorts what is left.

    >>> canonical_url('HTTPS://Example.com:443/a/?utm_source=x&b=2&a=1#top')
    'https://example.com/a?a=1&b=2'
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip()
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    if parts.port and parts.port != default_port:
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
        and not k.lower().startswith(TRACKING_PARAM_PREFIXES)
    )
    path = parts.path.rstrip("/") if parts.path != "/" else ""
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def item_id(key: str) -> str:
    """A short, filesystem-safe, stable identifier for an item key.

    >>> item_id('https://example.com/a')
    '2dce0a4c50441bfc'
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def is_safe_id(identifier) -> bool:
    """Whether an identifier can be used as a store key (it becomes a file name).

    >>> is_safe_id('llama.cpp'), is_safe_id('../../etc'), is_safe_id('a/b'), is_safe_id('')
    (True, False, False, False)
    """
    identifier = str(identifier)
    return bool(_SAFE_ID_RE.match(identifier)) and ".." not in identifier


def timestamp_key(when) -> str:
    """A sortable store key for a moment, in UTC.

    >>> timestamp_key('2026-01-02T03:04:05+01:00')
    '20260102T020405Z'
    """
    return to_datetime(when).strftime("%Y%m%dT%H%M%SZ")


def slug(text: str) -> str:
    """A kebab-case identifier.

    >>> slug('Music AI (real-time)')
    'music-ai-real-time'
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
