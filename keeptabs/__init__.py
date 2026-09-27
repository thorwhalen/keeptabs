"""Technology watch (in French, "veille") for people who work with AI agents.

Describe the areas you want to follow as watch specifications, let a scheduled
``tick`` acquire and match what is new, and ask "what's new" whenever you like.

>>> from keeptabs import tick, whats_new, watch_mall, spec_store  # doctest: +SKIP
"""

from keeptabs.digest import deliver, make_digest, render_markdown, whats_new
from keeptabs.engine import tick
from keeptabs.fetchers import DEFAULT_FETCHERS
from keeptabs.matching import keyword_matcher
from keeptabs.spec import SpecError, normalize_spec
from keeptabs.stores import memory_mall, spec_store, watch_mall
