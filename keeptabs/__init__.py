"""Keep tabs on the subjects you care about (technology watch; in French, "veille").

Describe what to follow as watch specifications, let a scheduled ``tick`` acquire
and match what is new, and ask "what's new" whenever you like.

By watch id, with everything on its default (this is what the command line runs):

>>> from keeptabs import tools
>>> tools.tick()  # doctest: +SKIP
>>> tools.whats_new('gen-ai', since='3d')  # doctest: +SKIP

With parts of your own (stores, fetchers, a matcher, a summarizer, senders):

>>> from keeptabs import tick, whats_new, make_digest  # doctest: +SKIP
"""

from keeptabs import tools
from keeptabs.digest import (
    deliver,
    escape_text,
    make_digest,
    render_markdown,
    scheduled_digest,
    whats_new,
)
from keeptabs.engine import AlreadyRunning, tick
from keeptabs.fetchers import DEFAULT_FETCHERS, Response, http_get
from keeptabs.matching import keyword_matcher
from keeptabs.spec import SpecError, normalize_spec
from keeptabs.stores import memory_mall, spec_store, watch_mall

__all__ = [
    "AlreadyRunning",
    "DEFAULT_FETCHERS",
    "Response",
    "SpecError",
    "deliver",
    "escape_text",
    "http_get",
    "keyword_matcher",
    "make_digest",
    "memory_mall",
    "normalize_spec",
    "render_markdown",
    "scheduled_digest",
    "spec_store",
    "tick",
    "tools",
    "watch_mall",
    "whats_new",
]
