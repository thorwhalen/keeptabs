"""The one-command test: a spec goes in, a tick runs, "what's new" answers."""

import json
from datetime import timedelta

import pytest

from keeptabs import spec_store, tick, watch_mall, whats_new, normalize_spec
from keeptabs.digest import make_digest, render_markdown, scheduled_digest
from keeptabs.util import to_datetime

T0 = to_datetime("2026-01-07T09:00:00+00:00")


def _run(rootdir, web, *, now=T0, **kwargs):
    return tick(rootdir=rootdir, http_get=web, now=now, **kwargs)


@pytest.fixture
def watch(rootdir, spec):
    spec_store(rootdir)["gen-ai"] = spec
    return rootdir


def test_a_tick_acquires_matches_and_stores(watch, web):
    result = _run(watch, web)
    assert result["ok"] and result["sources_run"] == 3
    items = watch_mall("gen-ai", rootdir=watch)["items"]
    titles = {item["title"] for item in items.values()}
    assert "Introducing Sprout, a small language model" in titles
    assert "example-lab/sprout v1.2.0" in titles  # kept by keep_all, with no keyword in it
    assert not any("coffee" in title for title in titles)  # irrelevant, so dropped


def test_the_same_document_is_stored_once(watch, web):
    _run(watch, web)
    items = list(watch_mall("gen-ai", rootdir=watch)["items"].values())
    sprout = [i for i in items if i["url"] == "https://blog.example.org/sprout"]
    assert len(sprout) == 1  # the feed link had a tracking parameter, Hacker News a fragment


def test_a_second_tick_does_nothing_until_a_source_is_due(watch, web):
    _run(watch, web)
    calls = len(web.calls)
    assert _run(watch, web, now=T0 + timedelta(hours=1))["sources_run"] == 0
    assert len(web.calls) == calls
    later = _run(watch, web, now=T0 + timedelta(hours=13))
    assert [run["source"] for run in later["runs"]] == ["hn"]
    assert later["items_kept"] == 0  # nothing new: every item was already stored


def test_feeds_are_fetched_conditionally(watch, web):
    _run(watch, web)
    _run(watch, web, now=T0 + timedelta(days=2))
    blog_calls = [call for call in web.calls if "blog.example.org/feed" in call["url"]]
    assert [call["etag"] for call in blog_calls] == [None, "v1"]


def test_one_broken_source_does_not_stop_the_others(watch, web):
    web.broken.add("hn.algolia.com")
    result = _run(watch, web)
    assert not result["ok"]
    assert [failure["source"] for failure in result["failures"]] == ["hn"]
    assert result["items_kept"] == 3
    state = watch_mall("gen-ai", rootdir=watch)["state"]["source--hn"]
    assert state["failures"] == 1 and "ConnectionError" in state["last_error"]


def test_a_source_waiting_on_the_human_is_not_run(watch, web, spec):
    spec["pending_actions"] = [{"action": "Subscribe to the newsletter", "blocks": ["hn"]}]
    spec_store(watch)["gen-ai"] = spec
    assert {run["source"] for run in _run(watch, web)["runs"]} == {"blog", "releases"}


def test_whats_new_groups_by_subtopic_and_links_only_stored_items(watch, web, spec):
    _run(watch, web)
    mall = watch_mall("gen-ai", rootdir=watch)
    data = whats_new(normalize_spec(spec), mall, since="2026-01-01", now=T0)
    assert [section["id"] for section in data["sections"]][:2] == ["language-models", "video"]
    assert data["new_entities"][0]["name"] == "Sprout"
    json.dumps(data)  # JSON-ready, so any surface can carry it
    text = render_markdown(data)
    stored_urls = {item["url"] for item in mall["items"].values()}
    import re

    assert set(re.findall(r"\]\((https?://[^)]+)\)", text)) <= stored_urls
    assert whats_new(normalize_spec(spec), mall, since=T0 + timedelta(minutes=1), now=T0 + timedelta(hours=1))["total_new"] == 0


def test_a_digest_is_a_dry_run_unless_told_to_send(watch, web, spec):
    _run(watch, web)
    sent = []

    def sender(ref, text, *, title, dry_run):
        sent.append((ref, dry_run))
        return {"ok": True}

    mall = watch_mall("gen-ai", rootdir=watch)
    digest = make_digest(normalize_spec(spec), mall, now=T0, senders={"test": sender})
    assert sent == [("test:somewhere", True)]
    assert mall["digests"][digest["key"]]["text"].startswith("# What's new: Generative AI")
    make_digest(normalize_spec(spec), mall, now=T0, senders={"test": sender}, send=True)
    assert sent[-1] == ("test:somewhere", False)


def test_the_scheduled_digest_comes_after_one_period_and_respects_auto_send(watch, web, spec):
    sent = []
    on_due = scheduled_digest(senders={"test": lambda ref, text, *, title, dry_run: sent.append(dry_run) or {"ok": True}})
    assert _run(watch, web, on_digest_due=on_due)["digests"] == []
    week_later = _run(watch, web, now=T0 + timedelta(days=7, minutes=1), on_digest_due=on_due)
    assert week_later["digests"][0]["total_new"] == 4
    assert sent == [True] and not week_later["digests"][0]["sent"]  # auto_send is off by default, so nothing left the machine
