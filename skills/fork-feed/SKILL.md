---
name: fork-feed
description: Report which of a GitHub user's or org's forks are behind, ahead, diverged from or identical to upstream, and list only the upstream commits not seen since the last run. Read-only. Use for "are my forks up to date", "what changed upstream", "which forks need syncing".
---

# fork-feed

Use fork-feed when someone asks whether their forks are current, which ones need syncing, or what changed upstream since they last checked. Run the CLI; do not open each repository page.

## Commands (run from the repo root; Python 3.9+, no dependencies)

```bash
GH_TOKEN=$(gh auth token) python fork_feed.py USER                 # all forks owned by USER (user or org)
python fork_feed.py USER --days 30                                 # first look at a feed: last 30 days
python fork_feed.py USER --fresh                                   # ignore what was seen; window only
python fork_feed.py USER --state ~/.fork-feed.json                 # where "seen" is remembered
```

A token is required (GitHub GraphQL); read-only access is enough. Exit code 2 means no token, a bad token or an unknown user.

## Reading the report
- `behind N (and M own)`: upstream has N commits the fork lacks; the fork also has M of its own.
- `contains upstream (+M own)`: nothing to sync.
- `diverged: no common ancestor`: history was rewritten; syncing would overwrite.
- `upstream gone`, `not checked: <reason>`: say so; never call these up to date.
- Under each lagging upstream: only commits not seen in earlier runs (first run: the last `--days`).

## Rules
- Read-only. Never sync, merge or push on the user's behalf unless they ask, and then use their normal git or `gh repo sync` flow.
- Quote commit titles as given; do not summarize them into claims about what upstream fixed.
