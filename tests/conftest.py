"""Shared fixtures: an offline network and a throwaway data root."""

from pathlib import Path

import pytest

from keeptabs.fetchers import Response

DATA = Path(__file__).parent / "data"

ROUTES = {
    "blog.example.org/feed": "feed.xml",
    "releases.atom": "releases.atom",
    "hn.algolia.com": "hackernews.json",
}


class FakeWeb:
    """An ``http_get`` that serves the files in ``tests/data`` and records calls."""

    def __init__(self):
        self.calls = []
        self.broken = set()

    def __call__(self, url, *, etag=None, last_modified=None, timeout=None):
        self.calls.append({"url": url, "etag": etag})
        for fragment in self.broken:
            if fragment in url:
                raise ConnectionError(f"cannot reach {fragment}")
        if etag == "v1":
            return Response(304)
        for fragment, filename in ROUTES.items():
            if fragment in url:
                return Response(200, (DATA / filename).read_bytes(), {"etag": "v1"})
        raise AssertionError(f"The test made an unexpected request: {url}")


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def rootdir(tmp_path, monkeypatch):
    monkeypatch.delenv("KEEPTABS_ROOTDIR", raising=False)
    return str(tmp_path / "keeptabs")


SPEC = {
    "id": "gen-ai",
    "title": "Generative AI",
    "keywords": ["generative AI", "diffusion model"],
    "subtopics": [
        {"id": "language-models", "title": "Language models", "priority": "high", "keywords": ["LLM", "language model"]},
        {"id": "video", "title": "Video generation", "keywords": ["text-to-video", "video generation"]},
    ],
    "entities": [{"name": "Sprout", "kind": "model"}],
    "sources": [
        {"kind": "feed", "id": "blog", "url": "https://blog.example.org/feed.xml", "cadence": "1d"},
        {"kind": "github_releases", "id": "releases", "repo": "example-lab/sprout", "cadence": "1d", "keep_all": True},
        {"kind": "hackernews", "id": "hn", "query": "generative AI", "cadence": "12h"},
    ],
    "digest": {"cadence": "1w", "channels": ["test:somewhere"]},
}


@pytest.fixture
def spec():
    from copy import deepcopy

    return deepcopy(SPEC)
