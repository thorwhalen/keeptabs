---
name: keeptabs-dev-scheduling-digests
description: How the scheduled run and the digests work in the keeptabs package, and the researched options behind them - due-ness from stored state, backoff, locking, launchd, cron and systemd, digest structure, model-written summaries with grounded citations, and delivery by email, Slack and GitHub Discussions. Use when changing tick, cadence or backoff, adding a scheduler installer, adding a delivery channel, adding a model-based summarizer, or debugging a digest that did not arrive.
metadata:
  audience: developers
---

# keeptabs: scheduling and digests

## Scheduling

There is no daemon. `tick` computes what is due from the `state` store: each source has `next_due`, set to now plus its cadence after a success, and to now plus the cadence times a doubling factor (capped by `MAX_BACKOFF_FACTOR`) after a failure. A `filelock` lock prevents two ticks at once, and the operating system releases it when the process ends. `keeptabs schedule` prints a scheduler entry; it installs nothing.

Tests pass `now=` to `tick`. Never call the clock directly in the engine.

## Digests

`whats_new` returns data. A summarizer turns it into text, and `render_markdown` is the default with no model. A model-based summarizer must cite item ids and let code resolve them to URLs; `test_whats_new_groups_by_subtopic_and_links_only_stored_items` is the guard.

A watch's first digest comes one full period after its first tick. A period with nothing new is skipped. A dry run changes no state. Items count as reported when a digest was sent and every channel took it, or when the scheduled run wrote a digest for a watch that has no channel. With channels and no `auto_send`, the scheduled run marks nothing: the items wait for the owner's send. The ids reported last are kept in the `digest` state, so an item acquired in the same second as a digest is not lost.

## Delivery

A channel is a reference such as `email:someone@example.org`. `deliver` looks up the sender by the part before the colon. Email, GitHub, ntfy and Telegram go through `correspond`, so they pass its `before_send` check. Slack posts to an incoming webhook whose URL is read from `KEEPTABS_SLACK_WEBHOOK_URL` (or that name plus a suffix), never from a variable the spec names freely; replace it with `correspond` when its Slack channel exists (correspond issue 3).

`deliver` is a dry run unless `dry_run=False`. The scheduled digest sends only when the spec has `digest.auto_send: true`.

## References

- `references/scheduling.md`: schedulers, due-ness, adaptive polling, backoff, failure handling.
- `references/digests-delivery.md`: digest generation, citation grounding, and delivery channels.
