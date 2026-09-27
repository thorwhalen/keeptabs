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
        http_get=web, now=T0,
    )  # fmt: skip
    assert result["ok"] and len(malls["gen-ai"]["items"]) == 4
    assert not (tmp_path / "must-stay-empty").exists()


def test_a_dry_run_changes_nothing_so_the_send_that_follows_is_not_empty(rootdir, web, spec):
    spec_store(rootdir)["gen-ai"] = spec
    tick(rootdir=rootdir, http_get=web)  # at the real time, as the tools run
    state = dict(watch_mall("gen-ai", rootdir=rootdir)["state"])
    first = tools.digest("gen-ai", rootdir=rootdir)
    second = tools.digest("gen-ai", rootdir=rootdir)
    assert first["total_new"] == second["total_new"] == 4
    assert dict(watch_mall("gen-ai", rootdir=rootdir)["state"]) == state


def _add_item(mall, name, when):
    mall["items"][name] = {"id": name, "title": f"LLM news {name}", "url": f"https://example.org/{name}", "acquired": when.isoformat(), "score": 1}


def _ok_sender(log):
    def send(ref, text, *, title, dry_run):
        log.append({"dry_run": dry_run, "text": text})
        return {"ok": True}

    return send


def test_an_item_is_reported_in_one_scheduled_digest_only(web, spec):
    spec["digest"] = {"cadence": "1d", "channels": ["test:somewhere"], "auto_send": True}
    mall, sent = memory_mall(), []
    on_due = scheduled_digest(senders={"test": _ok_sender(sent)})
    for day in range(4):
        now = T0 + timedelta(days=day, minutes=day)
        _add_item(mall, f"item{day}", now)  # acquired in the very second the digest is written
        tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=now, on_digest_due=on_due)
    reported = [name for name in ("item0", "item1", "item2", "item3") for s in sent if f"/{name})" in s["text"]]
    assert reported == ["item0", "item1", "item2", "item3"]
    assert not any(s["dry_run"] for s in sent)


def test_without_auto_send_the_items_wait_for_the_owner_to_send(web, spec):
    spec["sources"] = []
    spec["digest"] = {"cadence": "1d", "channels": ["test:somewhere"]}
    mall, sent = memory_mall(), []
    senders = {"test": _ok_sender(sent)}
    tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=T0, on_digest_due=scheduled_digest(senders=senders))
    _add_item(mall, "item0", T0 + timedelta(hours=1))
    later = T0 + timedelta(days=1, minutes=1)
    [scheduled] = tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=later, on_digest_due=scheduled_digest(senders=senders))["digests"]
    assert scheduled["total_new"] == 1 and not scheduled["sent"] and not scheduled["reported"]
    assert all(s["dry_run"] for s in sent)  # nothing left the machine
    manual = make_digest(normalize_spec(spec), mall, now=later + timedelta(hours=2), send=True, senders=senders)
    assert manual["total_new"] == 1 and manual["sent"] and "/item0)" in sent[-1]["text"]
    assert make_digest(normalize_spec(spec), mall, now=later + timedelta(hours=3), senders=senders)["total_new"] == 0


def test_a_digest_that_did_not_arrive_is_sent_again(web, spec):
    spec["digest"] = {"cadence": "1d", "channels": ["test:somewhere"]}
    mall = memory_mall()
    _add_item(mall, "item0", T0)

    def refuse(ref, text, *, title, dry_run):
        raise ConnectionError("the channel is down")

    failed = make_digest(normalize_spec(spec), mall, since="1d", now=T0, send=True, senders={"test": refuse})
    assert not failed["sent"] and not failed["reported"] and "digest" not in mall["state"]
    sent = []
    again = make_digest(normalize_spec(spec), mall, now=T0 + timedelta(hours=1), send=True, senders={"test": _ok_sender(sent)})
    assert again["sent"] and again["total_new"] == 1


@pytest.mark.parametrize("field", ["sources", "entities", "subtopics"])
def test_an_id_cannot_leave_its_store(field, spec):
    spec[field][0]["id"] = "../../../escaped"
    with pytest.raises(SpecError, match="ids become file names"):
        normalize_spec(spec)


def test_a_hand_written_spec_is_read_as_meant():
    spec = normalize_spec(
        {"id": "w", "keywords": "diffusion", "min_score": "2", "enabled": "false", "digest": "1d", "entities": ["Sora", {"name": "Magenta", "aliases": "Magenta RT"}],
         "subtopics": ["Video generation"], "sources": ["https://example.org/feed.xml"]}
    )  # fmt: skip
    assert spec["keywords"] == ["diffusion"] and spec["min_score"] == 2.0 and spec["enabled"] is False
    assert [e["id"] for e in spec["entities"]] == ["sora", "magenta"] and spec["entities"][1]["aliases"] == ["Magenta RT"]
    assert spec["subtopics"][0]["id"] == "video-generation" and spec["sources"][0]["kind"] == "feed"
    assert spec["digest"]["cadence"] == "1d"


@pytest.mark.parametrize(
    "fields",
    [
        {"keywords": [False, 3.10]},  # YAML's reading of NO and of 3.10: the text is lost, so it is refused
        {"min_score": "high"},
        {"min_score": float("nan")},
        {"enabled": "maybe"},
        {"sources": 5},
        {"sources": [5]},
        {"pending_actions": [5]},
        {"digest": {"max_items": 0}},
        {"digest": {"cadence": "soon"}},
        {"entities": [{"name": "X", "id": "CON"}]},
        {"sources": [{"kind": "feed", "url": "https://example.org/f", "id": "x" * 300}]},
    ],
)
def test_what_cannot_work_is_refused_with_a_reason(fields):
    with pytest.raises(SpecError):
        normalize_spec({"id": "w", **fields})


def test_two_targets_never_share_an_automatic_id():
    sources = [{"kind": "feed", "url": "https://x.example/a/b"}, {"kind": "feed", "url": "https://x.example/a-b"}]
    ids = [s["id"] for s in normalize_spec({"id": "w", "sources": sources})["sources"]]
    assert len(set(ids)) == 2


def test_stray_files_among_the_specs_are_not_watches(rootdir, web, spec):
    from pathlib import Path

    specs = spec_store(rootdir)
    specs["gen-ai"] = spec
    folder = Path(rootdir) / "specs"
    for name in ("Foo_Bar.yaml", "gen-ai.yaml~", "notes.txt", "x.yml"):
        (folder / name).write_text("title: stray\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "y.yaml").write_text("title: stray\n", encoding="utf-8")
    assert list(spec_store(rootdir)) == ["gen-ai"]
    assert [w["id"] for w in tools.watches(rootdir=rootdir)["watches"]] == ["gen-ai"]
    specs["broken"] = {"min_score": "high"}
    listing = tools.watches(rootdir=rootdir)
    assert not listing["ok"] and {w["id"]: "error" in w for w in listing["watches"]} == {"broken": True, "gen-ai": False}
    assert tools.pending(rootdir=rootdir)["unreadable"][0]["watch"] == "broken"
    assert tools.due(rootdir=rootdir)["unreadable"][0]["watch"] == "broken"
    with pytest.raises(KeyError):
        watch_mall("../escape", rootdir=rootdir)


def test_stores_of_your_own_come_in_a_pair(web, spec):
    with pytest.raises(ValueError, match="without malls="):
        tick(specs={"gen-ai": spec}, http_get=web, now=T0)


@pytest.mark.parametrize("patch", ["[1]", "not json", '{"sources": 5}', '{"pending_actions": [5]}', '{"id": "other"}'])
def test_a_bad_patch_is_refused_with_a_reason(rootdir, patch):
    tools.init_watch("W", rootdir=rootdir, overwrite=True)
    with pytest.raises(SpecError):
        tools.edit_watch("w", patch, rootdir=rootdir)


def test_the_tools_can_run_twice(rootdir, web):
    tools.init_watch("W", rootdir=rootdir)
    assert tools.tick(rootdir=rootdir)["ok"] and tools.tick(rootdir=rootdir)["ok"]


def test_a_scheduler_entry_survives_spaces_in_paths(monkeypatch):
    monkeypatch.setenv("KEEPTABS_ROOTDIR", "/data/my watch & co")
    assert "'/data/my watch & co'" in tools.schedule(kind="cron")["text"]
    assert "my watch &amp; co" in tools.schedule(kind="launchd")["text"]
    with pytest.raises(ValueError):
        tools.schedule(kind="cron", every_minutes=45)


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


def test_fetched_text_cannot_ping_people_or_start_a_heading():
    hostile = {"id": "x", "title": "Thanks @someone and @org/team, see #12\n# Big heading", "url": "https://example.org/a", "acquired": T0.isoformat(), "score": 1}
    mall = memory_mall()
    mall["items"]["x"] = hostile
    text = render_markdown(whats_new(normalize_spec({"id": "w"}), mall, since="1d", now=T0))
    assert "@" not in text and "#12" not in text
    assert [line for line in text.splitlines() if line.startswith("#")] == ["# What's new: w", "## Other"]


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
    assert created["spec"]["digest"]["channels"] == []  # nor can it choose who receives them


def test_a_matcher_sees_the_stores_and_may_name_new_things(web, spec):
    mall = memory_mall()

    def matcher(item, spec, *, mall):
        repeated = next((i["id"] for i in mall["items"].values() if i["title"][:12] == item["title"][:12]), None)
        return {"score": 5, "subtopics": [], "entities": ["a-new-thing"], "matched": [], "duplicate_of": repeated}

    spec["sources"] = [s for s in spec["sources"] if s["id"] in ("blog", "hn")]
    result = tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=T0, matcher=matcher)
    assert result["ok"]
    assert mall["entities"]["a-new-thing"]["kind"] == "candidate"
    assert all(d["reason"] == "duplicate" for d in mall["dropped"].values())
    calls = []
    tick(specs={"gen-ai": spec}, malls=lambda _: mall, http_get=web, now=T0 + timedelta(days=3),
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
