"""What an independent review broke, kept broken-proof."""

import contextlib
from datetime import timedelta

import pytest

from keeptabs import memory_mall, normalize_spec, spec_store, tick, tools, watch_mall, whats_new
from keeptabs.digest import deliver, make_digest, render_markdown, scheduled_digest
from keeptabs.spec import SpecError
from keeptabs.util import to_datetime

T0 = to_datetime("2026-01-07T09:00:00+00:00")


def test_a_new_source_kind_needs_only_a_fetcher(rootdir, web, spec):
    spec["sources"] = [{"kind": "my_api", "target": "robots", "keep_all": True}]
    spec_store(rootdir)["gen-ai"] = spec

    def fetch(source, *, state, http_get):
        return [{"url": f"https://api.example.org/{source['target']}/1", "title": "A robot"}], state

    assert tick(rootdir=rootdir, http_get=web, now=T0, fetchers={"my_api": fetch})["items_kept"] == 1
    no_fetcher = tick(rootdir=rootdir, http_get=web, now=T0, force=True)
    assert "No fetcher for source kind 'my_api'" in no_fetcher["failures"][0]["error"]


def test_data_can_live_anywhere_and_nothing_is_written_locally(tmp_path, monkeypatch, web, spec):
    monkeypatch.setenv("KEEPTABS_ROOTDIR", str(tmp_path / "must-stay-empty"))
    malls = {}
    result = tick(
        specs={"gen-ai": spec}, malls=lambda watch_id: malls.setdefault(watch_id, memory_mall()),
        http_get=web, now=T0, lock=False,
    )  # fmt: skip
    assert result["ok"] and len(malls["gen-ai"]["items"]) == 4
    assert not (tmp_path / "must-stay-empty").exists()


def test_a_dry_run_changes_nothing_so_the_send_that_follows_is_not_empty(rootdir, web, spec):
    spec_store(rootdir)["gen-ai"] = spec
    tick(rootdir=rootdir, http_get=web)  # at the real time, as the tools run
    first = tools.digest("gen-ai", rootdir=rootdir)
    second = tools.digest("gen-ai", rootdir=rootdir)
    assert first["total_new"] == second["total_new"] == 4
    assert "digest" not in watch_mall("gen-ai", rootdir=rootdir)["state"]


def test_an_item_is_reported_in_one_scheduled_digest_only(web, spec):
    spec["digest"]["cadence"] = "1d"
    mall = memory_mall()
    reported = []
    on_due = scheduled_digest(senders={"test": lambda *a, **k: {"ok": True}})
    for day in range(4):
        now = T0 + timedelta(days=day, minutes=day)
        mall["items"][f"item{day}"] = {"id": f"item{day}", "title": f"LLM news {day}", "url": f"https://example.org/{day}", "acquired": now.isoformat(), "score": 1}
        result = tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=now, lock=False, on_digest_due=on_due)
        reported += [i for d in result["digests"] for i in mall["digests"][d["key"]]["item_ids"] if i.startswith("item")]
    assert sorted(reported) == sorted(set(reported)) and len(reported) >= 3


@pytest.mark.parametrize("field", ["sources", "entities", "subtopics"])
def test_an_id_cannot_leave_its_store(field, spec):
    spec[field][0]["id"] = "../../../escaped"
    with pytest.raises(SpecError, match="ids become file names"):
        normalize_spec(spec)


def test_a_hand_written_spec_is_read_as_meant():
    spec = normalize_spec({"id": "w", "keywords": "diffusion", "min_score": "2", "subtopics": [{"id": "s", "keywords": [False, 3.11]}], "entities": [{"name": "Magenta", "aliases": "Magenta RT"}]})
    assert spec["keywords"] == ["diffusion"] and spec["min_score"] == 2.0
    assert spec["subtopics"][0]["keywords"] == ["False", "3.11"]
    assert spec["entities"][0]["aliases"] == ["Magenta RT"]
    with pytest.raises(SpecError):
        normalize_spec({"id": "w", "min_score": "high"})


def test_one_broken_watch_does_not_stop_the_others(rootdir, web, spec):
    specs = spec_store(rootdir)
    specs["a-broken"] = {"subtopics": [{"id": "s", "priority": "urgent"}]}
    specs["gen-ai"] = spec
    result = tick(rootdir=rootdir, http_get=web, now=T0)
    assert result["items_kept"] == 4 and not result["ok"]
    assert [f["watch"] for f in result["failures"]] == ["a-broken"]
    unknown = tick(["nope"], rootdir=rootdir, http_get=web, now=T0)
    assert "No watch named 'nope'" in unknown["failures"][0]["error"]


def test_fetched_text_cannot_add_links_or_mentions_to_a_digest():
    hostile = {"id": "x", "title": "Sprout <!channel> [click](https://evil.example) <img onerror=x>", "url": "https://example.org/a b)c", "summary": "[more](https://evil.example)", "acquired": T0.isoformat(), "score": 1, "source": "s"}
    mall = memory_mall()
    mall["items"]["x"] = hostile
    text = render_markdown(whats_new(normalize_spec({"id": "w"}), mall, since="1d", now=T0))
    import re

    links = re.findall(r"(?<!\\)\[(?:\\.|[^\]\\])*\]\((https?://[^)\s]+)\)", text)  # as Markdown reads it
    assert links == ["https://example.org/a%20b%29c"]
    assert "<!channel>" not in text and "<img" not in text


def test_slack_reads_only_its_own_variable_and_never_shows_it(monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "sk-live-123456")
    monkeypatch.setenv("KEEPTABS_SLACK_WEBHOOK_URL_TEAM", "sk-live-654321")
    for ref in ("slack:SOME_SECRET", "slack:team", "slack:"):
        [result] = deliver("text", [ref], title="t", dry_run=True)
        assert not result["ok"] and "sk-live" not in str(result)
    monkeypatch.setenv("KEEPTABS_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    assert deliver("text", ["slack:"], title="t", dry_run=True)[0]["ok"]


def test_an_imported_spec_cannot_turn_on_sending(rootdir, tmp_path):
    path = tmp_path / "foreign.yaml"
    path.write_text("title: Foreign\ndigest:\n  channels: ['email:someone@example.org']\n  auto_send: true\n", encoding="utf-8")
    created = tools.init_watch("Foreign", spec_file=str(path), rootdir=rootdir)
    assert created["spec"]["digest"]["auto_send"] is False and created["notes"]


def test_a_matcher_sees_the_stores_and_may_name_new_things(web, spec):
    mall = memory_mall()

    def matcher(item, spec, *, mall):
        repeated = next((i["id"] for i in mall["items"].values() if i["title"][:12] == item["title"][:12]), None)
        return {"score": 5, "subtopics": [], "entities": ["a-new-thing"], "matched": [], "duplicate_of": repeated}

    spec["sources"] = [s for s in spec["sources"] if s["id"] in ("blog", "hn")]
    result = tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=T0, lock=False, matcher=matcher)
    assert result["ok"]
    assert mall["entities"]["a-new-thing"]["kind"] == "candidate"
    assert all(d["reason"] == "duplicate" for d in mall["dropped"].values())
    calls = []
    tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=T0 + timedelta(days=3), lock=False,
         matcher=lambda item, spec, *, mall: calls.append(item) or matcher(item, spec, mall=mall))  # fmt: skip
    assert calls == []  # what was judged once, kept or dropped, is not judged again


def test_two_ticks_cannot_run_at_once_and_a_dead_one_leaves_no_lock(rootdir, web, spec):
    from keeptabs.engine import AlreadyRunning, tick_lock

    spec_store(rootdir)["gen-ai"] = spec
    with tick_lock(rootdir):
        with pytest.raises(AlreadyRunning):
            tick(rootdir=rootdir, http_get=web, now=T0)
    assert tick(rootdir=rootdir, http_get=web, now=T0)["ok"]
    assert tick(rootdir=rootdir, http_get=web, now=T0, lock=contextlib.nullcontext())["ok"]


def test_any_language_survives_the_stores(rootdir):
    specs = spec_store(rootdir)
    specs["w"] = {"id": "w", "title": "Veille — 音楽 ✓"}
    assert spec_store(rootdir)["w"]["title"] == "Veille — 音楽 ✓"


def test_adding_an_entity_again_keeps_what_was_known(rootdir):
    tools.init_watch("W", rootdir=rootdir)
    tools.add_entity("w", "Sprout", kind="model", url="https://example.org/sprout", aliases="Sprout LM", rootdir=rootdir)
    entity = tools.add_entity("w", "Sprout", aliases="sprout-lm", rootdir=rootdir)["entity"]
    assert entity["aliases"] == ["Sprout LM", "sprout-lm"] and entity["kind"] == "model" and entity["url"]
