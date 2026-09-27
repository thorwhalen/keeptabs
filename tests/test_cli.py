"""The command line reaches the same functions, with nothing of its own."""

import json
import subprocess
import sys

from keeptabs import tools


def _keeptabs(*args, rootdir):
    done = subprocess.run(
        [sys.executable, "-m", "keeptabs", *args, "--rootdir", rootdir, "--json"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_watch_grows_from_a_vague_idea(rootdir):
    created = _keeptabs("init-watch", "Gen AI", "--intent", "new generative models", rootdir=rootdir)
    assert created["spec"]["id"] == "gen-ai" and created["spec"]["sources"] == []
    _keeptabs("add-keywords", "gen-ai", "LLM, language model", "--subtopic", "Language models", rootdir=rootdir)
    _keeptabs("add-source", "gen-ai", "feed", "https://blog.example.org/feed.xml", "--source-id", "blog", rootdir=rootdir)
    _keeptabs("add-source", "gen-ai", "email", "news@example.org", "--source-id", "newsletter", rootdir=rootdir)
    _keeptabs("add-action", "gen-ai", "Subscribe to the Example newsletter", "--blocks", "newsletter", rootdir=rootdir)
    statuses = {row["source"]: row["status"] for row in _keeptabs("due", rootdir=rootdir)["sources"]}
    assert statuses == {"blog": "due", "newsletter": "blocked"}
    assert _keeptabs("pending", rootdir=rootdir)["count"] == 1
    _keeptabs("resolve-action", "gen-ai", "subscribe-to-the-example-newsletter", rootdir=rootdir)
    assert _keeptabs("pending", rootdir=rootdir)["count"] == 0


def test_the_shipped_example_is_a_valid_spec(rootdir):
    assert "gen-ai" in tools.examples()["examples"]
    spec = tools.init_watch("Generative AI", example="gen-ai", watch_id="gen-ai", rootdir=rootdir)["spec"]
    assert len(spec["sources"]) >= 3 and spec["digest"]["auto_send"] is False


def test_every_tool_is_documented_and_json_ready():
    for tool in tools.TOOLS:
        assert tool.__doc__ and len(tool.__doc__) > 30, tool.__name__
    assert tools.schedule(kind="cron")["text"].endswith("2>&1")
