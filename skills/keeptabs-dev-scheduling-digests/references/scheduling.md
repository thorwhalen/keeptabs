# Scheduling per-source acquisition cadences

Research note for the tech-watch ("veille") package design. Question: how should a Python package that runs on macOS laptops and Linux servers decide *when* to poll each source (feeds, newsletter inbox, web search, arXiv, GitHub, Hugging Face, blogs), and what should actually wake it up? Versions and dates below were checked on 2026-09-27.

## TL;DR

Do not ship a scheduler daemon. Ship one idempotent command, `<pkg> tick`. It reads per-source state from the store, works out which sources are due, runs them under a lock, writes state back atomically, and exits. Any external trigger can call it (launchd, systemd timer, cron, GitHub Actions, a Claude Code task, or a human). Because due-ness comes from stored state and not from the trigger, a missed, late, duplicated or coalesced trigger costs nothing: the next tick catches up. Add `<pkg> schedule install` to generate the platform-native trigger, adaptive per-source intervals, jittered backoff that honours `Retry-After`, per-source failure counters surfaced in the digest, and a per-tick cost budget for paid APIs. Core dependencies are `filelock` and the standard library. `croniter` is optional, only for cron-style cadences in specs.

## 1. The landscape of triggers and in-process schedulers

### 1.1 In-process Python schedulers

- **APScheduler 3.x** is the mature option: 3.11.3 was released 2026-06-28, and the license is MIT [1]. The repository is active, with commits in September 2026 [3]. It runs inside a long-lived process (`BlockingScheduler`/`BackgroundScheduler`) with optional persistent job stores.
- **APScheduler 4.0 is still alpha.** The latest pre-release is 4.0.0a6 (2025-04-27), and there has been no 4.0 final as of this writing [1]. Its migration guide calls it a redesign: `Task`/`Schedule`/`Job` are split apart, data stores are rebuilt so several schedulers and workers can share them, event brokers are new, and the two scheduler classes merge into one `Scheduler`. It also lists gaps "before the final v4.0 release", such as no import from 3.x job stores [2]. Do not build on 4.x yet. If we ever need APScheduler, pin `apscheduler>=3.11,<4`.
- **`schedule`** (MIT) is a tiny, human-friendly in-process loop (`schedule.every(10).minutes.do(job)`). Its last release was 1.2.2 on 2024-05-25 [4], and its last commit was on the same day [32]. It is stable but quiet. It has no persistence and no catch-up, so it is only suitable inside a daemon and adds nothing a `while True: tick(); sleep(60)` loop lacks.
- **Rocketry** (MIT) is effectively unmaintained. Its last release was 2.5.1 in December 2022 [33], and its last commit was 2023-02-28 [5]. Avoid it.
- **huey** (MIT, 3.4.0 released 2026-09-04, active) is a lightweight task queue with periodic tasks, but it needs a consumer process and a Redis, SQLite or file backend [6]. **Celery** (BSD-3-Clause, 5.6.3, 5.7.0a1 in September 2026) with celery-beat needs a broker and a beat process [7]. Both solve distributed work queues. That is the wrong problem for a single-user tool that polls a few dozen to a few hundred sources, so both are too heavy for the core. At most they fit as a future `executor=` seam.

### 1.2 OS and hosted triggers

- **cron** is available everywhere, but on macOS Apple calls it deprecated in favour of launchd. More importantly, "if the system is turned off or asleep, cron jobs do not execute; they will not run until the next designated time occurs" [8]. On a laptop that sleeps overnight, a daily 07:00 cron job simply does not run that day.
- **macOS launchd.** If a `StartCalendarInterval` job was due while the machine slept, "your job will run when the computer wakes up". "All other launchd jobs are skipped when the computer is turned off or asleep" [8]. Several missed intervals are "coalesced into one event upon wake from sleep" [9]. So you get one catch-up run, not N. A powered-off machine gets no catch-up [8]. Prefer `StartCalendarInterval` (for example, a list of `{Minute: 0}`, `{Minute: 15}`, ... entries) over `StartInterval` for the tick trigger. User agents live in `~/Library/LaunchAgents` and are loaded with `launchctl`.
- **systemd timers (Linux).** `Persistent=true` stores the last trigger time on disk. On activation, the service fires immediately "if it would have been triggered at least once during the time when the timer was inactive". This is the systemd answer to cron's missed-run problem. `OnCalendar=` takes calendar expressions. `RandomizedDelaySec=` adds a uniform random delay, and `FixedRandomDelay=` makes that delay stable per timer. `AccuracySec=` defaults to 1 min. `WakeSystem=` can resume from suspend [10]. For per-user timers on a headless server, the user needs lingering enabled (`loginctl enable-linger`) so the timer runs without a login session.
- **GitHub Actions `schedule`.** The minimum interval is 5 minutes. Runs "can be delayed during periods of high loads", especially at the start of every hour, and "some queued jobs may be dropped". In public repos, scheduled workflows are "automatically disabled when no repository activity has occurred in 60 days". They only run from the default branch. IANA timezones are supported [11]. State between runs has three options. (a) Commit it back to the repo. This also counts as activity, which keeps the schedule alive, but it publishes the state, which is not acceptable for private sources in a public repo. (b) Use the Actions cache. Entries not accessed in 7 days are evicted, caches are immutable (so use a new key per run plus a `restore-keys` prefix), and the default limit is 10 GB per repo [12]. (c) Use artifacts or external blob storage. GHA suits a "server-less" deployment of public-source watches. Because of the delays and drops, due-ness must live in state, not in the cron expression.
- **Claude Code scheduling.** Three flavours exist [13]. *Cloud routines* run on Anthropic infrastructure, need no machine, have a 1-hour minimum interval, and work on a fresh clone with no local files. *Desktop scheduled tasks* run locally, need the machine on, and have a 1-minute minimum interval. *Session `/loop`* tasks are session-scoped, expire after 7 days, and have "no catch-up for missed fires" [13]. For this package, the agent is best used for the *reasoning* layer (for example, "summarise what's new and publish the digest" once a day), triggered after or independently of `tick`. Acquisition should stay on a cheap deterministic trigger. A cloud routine can run `tick` only if the store is remote or committed. The local default `~/.local/share/<pkg>` is invisible to it.

## 2. Core design choice: stateful `tick` vs. long-running daemon

| Concern | Idempotent `tick` + external trigger | Long-running daemon (APScheduler/huey/loop) |
|---|---|---|
| Laptop sleep / reboot | Next tick recomputes due-ness from state and catches up | Needs its own misfire/catch-up logic, plus a supervisor to restart it |
| Process supervision | None (the OS trigger is the supervisor) | Needs launchd `KeepAlive` / systemd `Restart=` anyway |
| Memory/leaks over weeks | A fresh process each run | Accumulates |
| Upgrades | Take effect on the next tick | Need a restart |
| Portability to GHA / cloud agents | The same command works unchanged | Does not map to CI or serverless |
| Sub-minute latency / push (WebSub) | Poor (tick granularity) | Good |
| Debuggability | `tick --dry-run` prints what is due and why | Needs logs or introspection |

The tick model wins for this use case: minutes-to-days cadences, a single user, and laptops that sleep. The daemon becomes an optional *surface* later: `<pkg> run --every 60s` is just a loop around `tick()`, with no new core.

### 2.1 Due-ness

For each source, `next_due_at` is derived, never scheduled:

- After a success: `last_success_at + effective_interval + jitter`. `effective_interval` is the spec's cadence, adjusted adaptively (Section 3) and clamped to `[min_interval, max_interval]`.
- After a failure: `last_attempt_at + backoff(consecutive_failures)`, or later if the server sent `Retry-After` [23].
- If the spec gives a cron expression (for example "Mondays 08:00" for a weekly newsletter digest), use `croniter` (MIT, 6.2.4, released 2026-07-10) [28]: `next_due_at = croniter(expr, last_success_at).get_next()`. This is catch-up by construction: one run, no matter how many slots were missed.

Store `next_due_at` in the record as a *cache* of this computation, so `status` can list upcoming work cheaply. Always recompute it on write.

### 2.2 Locking, crash-safety, atomic writes

- **Global tick lock.** Take a non-blocking exclusive lock on `~/.local/share/<pkg>/tick.lock` at the start. If another tick holds it, exit 0 with "tick already running". Overlapping triggers (a launchd catch-up plus a manual run) are then harmless. **`filelock`** (MIT, 4.0.4, released 2026-09-26) picks `fcntl.flock` on Unix/macOS, which the kernel enforces and "released automatically on crash", and falls back to a cooperative soft lock elsewhere [14][30]. `portalocker` (BSD-3-Clause, 4.4.0, September 2026) is an alternative with Redis-backed locks for multi-host setups [15]. Raw `fcntl.flock` from the standard library is enough on the two target OSes. `filelock` is still worth its tiny footprint. Avoid locks on network filesystems (NFS or synced folders), and keep state out of Dropbox/iCloud directories.
- **Per-source leases (later seam).** If `tick` gains a thread pool, or several hosts share a remote store, record `lease_owner` and `lease_expires_at` in the source record instead of relying on the global lock. A crashed worker's lease simply expires.
- **Order of commits = at-least-once.** Fetch, then persist new items (keyed by a content hash or canonical URL, so re-writes are idempotent), then persist the source state. A crash between the two steps re-fetches next time and dedups. It never loses items. Never advance `last_success_at` before the items are durable.
- **Atomic record writes.** Write to a temp file in the same directory, call `flush()` and `os.fsync()`, then `os.replace(tmp, final)`. `os.replace` overwrites the destination and must stay on one filesystem [16]. Rename-over is atomic on POSIX, so readers see either the old record or the new one, never a torn JSON. Wrap this in the `MutableMapping` store's `__setitem__` so all state goes through one code path.

### 2.3 State record schema (one per source, `state/<source_id>.json`)

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceState:
    source_id: str  # "<tracked_id>/<source_key>"
    kind: str  # "rss" | "arxiv" | "github" | "imap" | "websearch" | ...
    # cadence
    base_interval_s: int  # from the spec
    min_interval_s: int = 300
    max_interval_s: int = 86_400
    effective_interval_s: Optional[int] = None  # adaptive estimate (None -> base)
    cron: Optional[str] = None  # alternative to interval
    # timing
    last_attempt_at: Optional[float] = None
    last_success_at: Optional[float] = None
    next_due_at: Optional[float] = None  # cached derivation
    not_before: Optional[float] = None  # Retry-After / Cache-Control floor
    # HTTP validators (conditional GET)
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    # health
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None
    status: str = "active"  # "active" | "backing_off" | "disabled"
    disabled_reason: Optional[str] = None
    # adaptivity inputs
    recent_item_times: list[float] = field(default_factory=list)  # capped ring, e.g. 50
    # accounting
    cost_last_run: float = 0.0
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[float] = None
    schema_version: int = 1
```

### 2.4 `tick()` sketch

```python
import random, time
from filelock import FileLock, Timeout


def tick(
    *,
    sources,
    state_store,
    item_store,
    fetchers,
    lock_path,
    now=time.time,
    budget=None,
    max_sources=None,
    dry_run=False,
    log=print,
):
    """Run every due source once. Safe to call at any frequency, from any trigger."""
    try:
        lock = FileLock(lock_path, timeout=0)
        lock.acquire()
    except Timeout:
        log("tick already running; exiting")
        return {"skipped": "locked"}
    try:
        t = now()
        due = sorted(
            (
                s
                for s in sources
                if _is_due(state_store.get(s.id) or _initial_state(s), t)
            ),
            key=lambda s: _overdue_by(state_store.get(s.id), t),
            reverse=True,  # most overdue first, so a budget cut hits the least urgent
        )[:max_sources]
        report = {"ran": [], "failed": [], "deferred": []}
        for src in due:
            st = state_store.get(src.id) or _initial_state(src)
            fetch = fetchers[st.kind]
            if budget and not budget.can_afford(fetch.estimate_cost(src)):
                report["deferred"].append(src.id)  # stays due; picked first next tick
                continue
            if dry_run:
                report["ran"].append(src.id)
                continue
            st.last_attempt_at = t
            try:
                result = fetch(src, etag=st.etag, last_modified=st.last_modified)
                for key, item in result.items:  # idempotent: content-keyed
                    item_store[key] = item
                if budget:
                    budget.charge(result.cost)
                _on_success(st, result, now())
                report["ran"].append(src.id)
            except Exception as e:  # classify in real code
                _on_failure(st, e, now())
                report["failed"].append((src.id, repr(e)))
            state_store[src.id] = st  # atomic write via the store
        return report
    finally:
        lock.release()


def _is_due(st, t):
    if st.status == "disabled":
        return False
    floor = max(st.next_due_at or 0, st.not_before or 0)
    return t >= floor


def _on_success(st, result, t):
    st.last_success_at, st.consecutive_failures, st.last_error = t, 0, None
    st.status = "active"
    st.etag, st.last_modified = result.etag, result.last_modified
    st.recent_item_times = (st.recent_item_times + result.item_times)[-50:]
    st.effective_interval_s = adaptive_interval(st, hints=result.hints)
    jitter = random.uniform(0, 0.1 * st.effective_interval_s)
    st.next_due_at = t + st.effective_interval_s + jitter
    st.not_before = result.not_before  # from Cache-Control / Retry-After
```

`tick` returns a report. The CLI prints it, and the digest builder reads the accumulated failures (Section 4).

## 3. Adaptive polling intervals

The spec's cadence should be a *default*, not a fixed rate. Prior art:

- **Miniflux** offers `POLLING_SCHEDULER=entry_frequency`, which sets each feed's interval from the number of entries in the past week, clamped between `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` (default 5 min) and `..._MAX_INTERVAL` (default 1440 min), with a `..._FACTOR` multiplier. The alternative `round_robin` mode has a 60-min minimum. Miniflux also stops polling a feed after `POLLING_PARSING_ERROR_LIMIT` (default 3) errors [18]. In short: interval ≈ one week ÷ (entries in the last week × factor).
- **`reader`** (BSD-3-Clause, 3.26, released 2026-06-24) [31] implements `update_feeds(scheduled=True)`. It runs only feeds due at or before now, with a per-feed configurable interval (default 1 h) and a jitter fraction. It also honours `Cache-Control: max-age`, `Expires` and `Retry-After` [17]. Its update model is close to the `tick` design above and worth reading. It could also be embedded as the RSS backend instead of re-implementing feed polling.
- **Feed-declared hints.** RSS 2.0 `<ttl>` is "a number of minutes that indicates how long a channel can be cached", and `<skipHours>`/`<skipDays>` are hints [19]. RSS 1.0's `sy:updatePeriod` (hourly…yearly, default daily) and `sy:updateFrequency` (times per period, default 1) give a declared publishing rate [20]. Treat them as a *floor* on the interval (do not poll faster than declared), not as a target, because many feeds publish boilerplate values.
- **Conditional GET.** Store `ETag`/`Last-Modified` and send `If-None-Match`/`If-Modified-Since`. A `304` costs almost nothing and counts as a success with zero items [23].
- **Push (WebSub).** WebSub is a W3C Recommendation. Publishers advertise a hub with `Link: rel="hub"`, the subscriber registers a callback, the hub verifies it with a `hub.challenge` GET, and leases expire and must be renewed [21]. The subscriber "must be directly network-accessible", which rules it out on a laptop behind NAT. Keep it as a server-only extension: an HTTP surface receives pushes into the item store, and the source's poll interval relaxes to `max_interval` as a safety net.

A suggested `adaptive_interval`:

```python
WEEK = 7 * 86_400


def adaptive_interval(st, *, hints, factor=1.0):
    recent = [x for x in st.recent_item_times if x >= (st.last_success_at or 0) - WEEK]
    est = WEEK / (len(recent) * factor) if recent else st.max_interval_s
    floor = max(st.min_interval_s, hints.get("ttl_s", 0), hints.get("sy_period_s", 0))
    return int(min(max(est, floor, st.base_interval_s * 0.25), st.max_interval_s))
```

API-style sources (arXiv listings, GitHub releases, HF models) have natural cadences. arXiv announces new listings once per weekday, so polling it hourly is waste. Encode such per-kind defaults in the fetcher, not in user specs.

## 4. Backoff, failures, and surfacing them

- **Backoff shape.** Use capped exponential backoff with *full jitter*: `sleep = uniform(0, min(cap, base * 2**n))`. AWS's analysis found full jitter the most efficient of the jittered variants [22]. At tick level this becomes `next_due_at = last_attempt_at + that`, not an in-process sleep.
- **Retry-After.** It may be an HTTP-date or delay-seconds [23]. Parse both, and set `not_before = max(computed_backoff, retry_after)` for 429/503. Never retry a 429 inside the same tick.
- **Libraries.** For *in-call* retries (transient connection resets within one fetch), use **`tenacity`** (Apache-2.0, 9.1.4, released 2026-02-07, repo active) [24] or **`stamina`** (MIT, 26.1.0, released 2026-04-13), an opinionated wrapper with jittered exponential defaults [26]. **`backoff`** (MIT) is **archived on GitHub**, with its last release 2.2.1 in 2022 [25]. Do not adopt it. Keep in-call retries small (2–3 attempts). Cross-tick backoff lives in state, and no library is needed for it.
- **Error classes.** Separate the retryable (timeouts, 5xx, 429) from the permanent (404/410, auth failure, parse error). Permanent errors count faster toward disabling. A `410 Gone` disables at once.
- **Circuit breaker = the state record.** `consecutive_failures` with statuses `active → backing_off → disabled` (after N, like Miniflux's limit of 3 for parse errors [18]; about 10 for network errors) already *is* a per-source circuit breaker, and it persists across processes. `pybreaker` (BSD, 1.4.1, 2025) [29] is in-memory and adds nothing for a short-lived process. A per-*host* breaker (for example, all of GitHub rate-limited) is worth adding by keying a small record on the hostname and checking it in `_is_due`.
- **Surface failures.** Each digest gets a "Source health" section listing sources disabled since the last digest, sources backing off for more than one day, and budget-deferred sources. `<pkg> status` shows the same information, and `<pkg> source enable <id>` resets a source. Silent rot of a watch list is the main failure mode of veille tools, so make it visible to the agent too (an MCP/CLI `health()` function).

## 5. Budgets for paid APIs

Web-search APIs and LLM-based matching or summarisation cost money per call. Put a `Budget` object behind a seam (`budget=`) with:

- a **per-tick cap** (currency or call count) and a **rolling per-day/month cap**, persisted in a `budget/` ledger in the same store and appended per charge;
- `estimate_cost(src)` on each fetcher, so `tick` decides *before* calling. Sources over budget are deferred, stay due, and are ordered first next time because they are the most overdue;
- a hard stop that never exceeds the cap even if an estimate was low. Charge the actual cost after the call, and stop the tick once the running total crosses the cap.
- Record deferrals in the tick report so the digest can say "3 paid searches deferred: monthly budget 92% used".

## 6. Cross-platform installer helpers

Provide `<pkg> schedule install [--every 15m] [--dry-run]`, `schedule uninstall`, and `schedule show`. Default to *printing* the artefact with `--dry-run`, then writing it only on request:

- **macOS:** write `~/Library/LaunchAgents/<reverse-dns>.<pkg>.tick.plist` with `ProgramArguments` set to the absolute path of the console script (launchd has no shell `PATH`), `StartCalendarInterval` as a list of minute entries for catch-up-on-wake [8][9], `StandardOutPath`/`StandardErrorPath` under `~/.local/state/<pkg>/` or the data dir, and `ProcessType=Background`. Then call `launchctl bootstrap gui/$UID <plist>`.
- **Linux:** write `~/.config/systemd/user/<pkg>-tick.{service,timer}`. The service is `Type=oneshot` with `ExecStart=<abs path> tick`. The timer has `OnCalendar=*:0/15`, `Persistent=true` and `RandomizedDelaySec=60` [10]. Run `systemctl --user enable --now <pkg>-tick.timer`, and suggest `loginctl enable-linger` on servers.
- **Fallback:** print a crontab line (`*/15 * * * * <abs path> tick >> <log> 2>&1`). `python-crontab` (LGPL-3.0, 3.4.0, 2026-08-29) [27] can edit the user crontab programmatically. It is optional; emitting the line keeps the dependency list clean and the license simple.
- **GitHub Actions:** `schedule init-gha` emits a workflow with an off-the-hour cron (for example `7,22,37,52 * * * *`, to avoid top-of-hour delays [11]), `actions/cache` restore/save of the state dir with a per-run key [12], and `workflow_dispatch` for manual runs.

Templates are plain strings or `string.Template` in the package, one module per platform behind a `platform=` strategy keyword that defaults to auto-detection via `sys.platform`.

## Recommendation

1. **Core = stateful, idempotent `tick()`**, exposed as `<pkg> tick`. There is no daemon in v1, and there is no scheduler library in core dependencies. Due-ness is derived from per-source `SourceState` records in the same `MutableMapping` store family as the data (`~/.local/share/<pkg>/state/`).
2. **Locking with `filelock`** (MIT, active). Use a non-blocking global lock, exit cleanly when it is held, write items before state (at-least-once plus content-keyed dedup), and do atomic temp+fsync+`os.replace` writes inside the store.
3. **Triggers via generated native units.** Use launchd `StartCalendarInterval` on macOS (catches up on wake) and a systemd user timer with `Persistent=true` + `RandomizedDelaySec` on Linux. cron is a fallback. GitHub Actions is an optional serverless mode for public sources only. Claude Code routines or desktop tasks drive the *digest and agent* layer, not acquisition.
4. **Adaptive cadence.** Use a Miniflux-style entry-frequency estimate clamped to spec min/max, with `ttl`/`sy:*`/`Cache-Control` as floors, conditional GET, and per-kind defaults. Consider `reader` as the RSS backend. WebSub is a later server-only surface.
5. **Failure handling in state.** Use full-jitter exponential backoff across ticks, honour `Retry-After`, keep per-source and per-host failure counters with auto-disable, and include a health section in every digest. Use `tenacity` or `stamina` for small in-call retries. Avoid `backoff` (archived) and Rocketry (unmaintained).
6. **Budget seam.** A `budget=` keyword with per-tick and rolling caps, pre-call estimates and post-call charging. Deferrals are reported.
7. **Keep APScheduler 3.x (`<4`) in reserve** for an optional `run --daemon` surface if sub-minute or push latency is ever needed. Do not adopt 4.0 until it leaves alpha.

### Comparison table

| Option | Version / date (checked 2026-09) | License | Maintained | Catch-up after sleep/off | Extra infra | Role in design |
|---|---|---|---|---|---|---|
| Stateful `tick` (own code) | n/a | (ours) | n/a | Yes, from state | None | **Core** |
| launchd `StartCalendarInterval` | macOS built-in | n/a | Yes | Sleep: yes, coalesced; off: no [8][9] | None | **macOS trigger** |
| systemd timer `Persistent=true` | Linux built-in | n/a | Yes | Yes [10] | None | **Linux trigger** |
| cron | built-in | n/a | Yes | No [8] | None | Fallback trigger |
| GitHub Actions schedule | hosted | n/a | Yes | Delays/drops; disabled after 60 days idle (public) [11] | Repo + cache/artifacts | Optional serverless mode |
| Claude Code routines / desktop tasks | hosted/local | n/a | Yes | Routine: 1 h min, no local files; `/loop`: no catch-up, 7-day expiry [13] | Claude plan | Digest/agent layer |
| APScheduler 3.x | 3.11.3, 2026-06-28 | MIT | Active | Misfire grace (in-process) | Daemon | Optional daemon surface |
| APScheduler 4.0 | 4.0.0a6, 2025-04 (alpha) | MIT | Active, pre-release | n/a | Daemon + store/broker | Avoid for now |
| schedule | 1.2.2, 2024-05 | MIT | Stable/quiet | No | Daemon | Not needed |
| Rocketry | 2.5.1, 2022-12 | MIT | **No** (last commit 2023-02) | n/a | Daemon | Avoid |
| huey | 3.4.0, 2026-09-04 | MIT | Active | Via consumer | Consumer + backend | Too heavy for core |
| Celery + beat | 5.6.3 (5.7.0a1) | BSD-3-Clause | Active | Via beat | Broker + beat + workers | Too heavy |
| filelock | 4.0.4, 2026-09-26 | MIT | Active | n/a | None | **Lock** |
| portalocker | 4.4.0, 2026-09-19 | BSD-3-Clause | Active | n/a | Optional Redis | Multi-host lock alternative |
| tenacity | 9.1.4, 2026-02-07 | Apache-2.0 | Active | n/a | None | In-call retries |
| stamina | 26.1.0, 2026-04-13 | MIT | Active | n/a | None | In-call retries (alt.) |
| backoff | 2.2.1, 2022-10 | MIT | **Archived** | n/a | None | Avoid |
| croniter | 6.2.4, 2026-07-10 | MIT | Active | n/a | None | Optional: cron cadences in specs |
| python-crontab | 3.4.0, 2026-08-29 | LGPL-3.0 | Active | n/a | None | Optional installer helper |
| reader | 3.26, 2026-06-24 | BSD-3-Clause | Active | Scheduled updates from state | SQLite | Candidate RSS backend / prior art |

## REFERENCES

[1] PyPI. APScheduler release history (JSON API). 2026. [pypi.org/pypi/APScheduler/json](https://pypi.org/pypi/APScheduler/json)

[2] A. Grönholm. APScheduler: Migrating from previous versions (4.0 docs). 2026. [apscheduler.readthedocs.io/en/master/migration.html](https://apscheduler.readthedocs.io/en/master/migration.html)

[3] GitHub. agronholm/apscheduler repository. 2026. [github.com/agronholm/apscheduler](https://github.com/agronholm/apscheduler)

[4] PyPI. schedule release history (JSON API). 2024. [pypi.org/pypi/schedule/json](https://pypi.org/pypi/schedule/json)


[5] GitHub. Miksus/rocketry repository. 2023. [github.com/Miksus/rocketry](https://github.com/Miksus/rocketry)

[6] PyPI / GitHub. huey release history and repository. 2026. [pypi.org/pypi/huey/json](https://pypi.org/pypi/huey/json), [github.com/coleifer/huey](https://github.com/coleifer/huey)

[7] PyPI. celery release history (JSON API). 2026. [pypi.org/pypi/celery/json](https://pypi.org/pypi/celery/json)

[8] Apple. Daemons and Services Programming Guide: Scheduling Timed Jobs. [developer.apple.com — Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)

[9] launchd.plist(5) manual page (mirror). [leancrew.com/all-this/man/man5/launchd.plist.html](https://leancrew.com/all-this/man/man5/launchd.plist.html)

[10] systemd project. systemd.timer(5) manual page (Arch Linux mirror). 2026. [man.archlinux.org/man/systemd.timer.5](https://man.archlinux.org/man/systemd.timer.5)

[11] GitHub. Events that trigger workflows: schedule. 2026. [docs.github.com — events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

[12] GitHub. Dependency caching reference. 2026. [docs.github.com — dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)

[13] Anthropic. Claude Code Docs: Run prompts on a schedule. 2026. [code.claude.com/docs/en/scheduled-tasks](https://code.claude.com/docs/en/scheduled-tasks)

[14] tox-dev. filelock documentation. 2026. [py-filelock.readthedocs.io](https://py-filelock.readthedocs.io/en/latest/)

[15] PyPI. portalocker release history (JSON API). 2026. [pypi.org/pypi/portalocker/json](https://pypi.org/pypi/portalocker/json)

[16] Python Software Foundation. os — Miscellaneous operating system interfaces (os.replace). 2026. [docs.python.org/3/library/os.html](https://docs.python.org/3/library/os.html)

[17] lemon24. reader User guide: updating feeds / scheduled updates. 2026. [reader.readthedocs.io/en/latest/guide.html](https://reader.readthedocs.io/en/latest/guide.html)

[18] Miniflux. Configuration parameters. 2026. [miniflux.app/docs/configuration.html](https://miniflux.app/docs/configuration.html)

[19] RSS Advisory Board. RSS 2.0 Specification. [rssboard.org/rss-specification](https://www.rssboard.org/rss-specification)

[20] RSS-DEV Working Group. RDF Site Summary 1.0 Modules: Syndication. [web.resource.org/rss/1.0/modules/syndication](https://web.resource.org/rss/1.0/modules/syndication/)

[21] W3C. WebSub (W3C Recommendation). [w3.org/TR/websub](https://www.w3.org/TR/websub/)

[22] M. Brooker (AWS). Exponential Backoff And Jitter. 2015. [aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)

[23] IETF. RFC 9110: HTTP Semantics (Retry-After; conditional requests). 2022. [rfc-editor.org/rfc/rfc9110.html](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after)

[24] PyPI / GitHub. tenacity release history and repository. 2026. [pypi.org/pypi/tenacity/json](https://pypi.org/pypi/tenacity/json), [github.com/jd/tenacity](https://github.com/jd/tenacity)

[25] GitHub. litl/backoff repository (archived). 2024. [github.com/litl/backoff](https://github.com/litl/backoff)

[26] PyPI / GitHub. stamina release history and repository. 2026. [pypi.org/pypi/stamina/json](https://pypi.org/pypi/stamina/json), [github.com/hynek/stamina](https://github.com/hynek/stamina)

[27] PyPI. python-crontab release history (JSON API). 2026. [pypi.org/pypi/python-crontab/json](https://pypi.org/pypi/python-crontab/json)

[28] PyPI. croniter release history (JSON API). 2026. [pypi.org/pypi/croniter/json](https://pypi.org/pypi/croniter/json)

[29] PyPI. pybreaker release history (JSON API). 2025. [pypi.org/pypi/pybreaker/json](https://pypi.org/pypi/pybreaker/json)

[30] PyPI. filelock release history (JSON API). 2026. [pypi.org/pypi/filelock/json](https://pypi.org/pypi/filelock/json)

[31] PyPI. reader release history (JSON API). 2026. [pypi.org/pypi/reader/json](https://pypi.org/pypi/reader/json)

[32] GitHub. dbader/schedule repository. 2024. [github.com/dbader/schedule](https://github.com/dbader/schedule)

[33] PyPI. rocketry release history (JSON API). 2022. [pypi.org/pypi/rocketry/json](https://pypi.org/pypi/rocketry/json)
