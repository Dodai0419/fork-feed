<div align="center">

# fork-feed

**See which of your GitHub forks are behind upstream, and only what landed upstream since you last looked.**

GitHub tells you "This branch is 4357 commits behind" one repo at a time. forkiq answers it for all your forks, but needs a GitHub App and a server; imozuru's watcher shows only what is new in a feed. fork-feed does both in one read-only command.

Works with **Claude Code** and **Codex**.

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Status: prototype](https://img.shields.io/badge/status-prototype-orange.svg)

</div>

## Quick start
```bash
git clone https://github.com/Dodai0419/fork-feed && cd fork-feed
GH_TOKEN=$(gh auth token) python fork_feed.py YOUR_GITHUB_USER
```
Real output for a user with 11 forks (shortened):
```
| fork | upstream | verdict | latest tag (fork / upstream) |
| tiangolo/docker-registry-proxy | rpardini/docker-registry-proxy | behind 126 (and 5 own) | 0.2.4 / 0.7.0 |
| tiangolo/pydantic | pydantic/pydantic | behind 4357 | v0.14 / v2.14.1 |
| tiangolo/uv | astral-sh/uv | behind 6935 | 0.4.17 / 0.13.1 |

## pydantic/pydantic: behind 4357, last 14 days
- 2026-10-15 [Bump speedate to v0.18.0 (#14007)](https://github.com/pydantic/pydantic/commit/902e9b6...)
- 2026-10-15 [Harden CI (#14000)](https://github.com/pydantic/pydantic/commit/e0fb2ce...)

11 forks: 11 behind.
```
Run it again and a feed with nothing new shrinks to one line with its latest commit. Offline demo with a fake GitHub: `python examples/demo.py`. Python 3.9+, standard library only. Needs a token (GitHub's GraphQL API does); read access is enough.

## The problem
- Forks go stale quietly; GitHub shows "N commits behind" only on each repo's own page.
- A plain upstream commit feed shows the same 20 commits every day.
- The fork dashboards that exist need a GitHub App, a server and write permissions.

## The solution
| Idea | Fixes |
|------|-------|
| **One GraphQL call** lists every fork with both default-branch heads and latest tags | No per-repo crawling; identical heads need no further call |
| **forkiq's verdicts**: same / behind N (and M own) / contains upstream (+M own) / diverged (no common ancestor) / upstream gone / not checked | One honest word per fork, never "up to date" when the check failed |
| **imozuru's seen-state** for each lagging upstream's commit feed: the first look shows the last `--days`, later looks only what you have not seen | A daily run shows news, not the same list |
| **Parallel and light**: compares and feeds 8 at a time; compare asks for page 2 of 1-commit pages, which drops GitHub's file list (950 KB to 17 KB for a fork 6935 commits behind) | Whole check of 11 forks in about 5 s |

Read-only: it never syncs, merges, or writes to GitHub. State is one local JSON file (`--state`, default `.fork-feed.json`).

## Use with Claude Code
```bash
/plugin marketplace add Dodai0419/fork-feed
/plugin install fork-feed@fork-feed
```
Then ask: "which of my forks are behind, and what changed upstream?"

## Use with Codex (ChatGPT)
```bash
git clone https://github.com/Dodai0419/fork-feed && cp -r fork-feed/skills/* ~/.codex/skills/
```
Or copy `AGENTS.md` into your project root.

## Benchmarks
`GH_TOKEN=$(gh auth token) python bench/bench.py <imozuru checkout> tiangolo 3`, live GitHub, 11 forks all behind, median of 3, Windows 11, Python 3.11.1. Network-bound: GitHub's compare endpoint alone takes 1 to 2 s per fork, so expect these to move.

| | time | what it does |
|-|-|-|
| imozuru `watch.py check` on the 11 upstream commit feeds | 1909 ms | feeds only, one after another; no behind/ahead counts |
| fork-feed `--jobs 1` | 15280 ms | list forks + 11 compares + 11 feeds, one after another (what the two upstream tools do in sequence) |
| fork-feed (default `--jobs 8`) | 5116 ms | the same work, 8 requests at a time |

| | upstream | fork-feed |
|-|-|-|
| lines of code | 1673 (forkiq versions.py 128, engine.py 936, github.py 300 + imozuru watch.py 309; forkiq also syncs forks, imozuru watches any RSS) | 238 (fork_feed.py) |
| dependencies | forkiq: web app, GitHub App, Linux (`fcntl`) | 0 |

forkiq's engine could not be run here (it needs a GitHub App and imports `fcntl`, which Windows lacks), so the comparison with forkiq is on its verdict function only. Same results, checked against the upstream code (`bench/golden.py`):
- `test_same_verdicts_as_forkiq`: forkiq's `version_verdict()` gives the same kind for all 11 rows (6 fake forks, 5 edge cases).
- `test_same_new_items_as_imozuru_watch`: on three looks at the same feed (first look, nothing new, one new commit) the new items equal what imozuru's `watch.py check` listed.

## Inspired by
- [zzusec/forkiq](https://github.com/zzusec/forkiq) (MIT): the compare probe (base = fork branch, head = upstream) and the verdict rules.
- [MaryCache/imozuru](https://github.com/MaryCache/imozuru) (MIT): RSS/Atom parsing with the DOCTYPE/ENTITY guard, the first-look window and the seen-links state.

## Roadmap
- [ ] Release feeds next to commit feeds.
- [ ] `--json` output for dashboards.

## License
MIT. See `LICENSE` for the upstream copyright notices.
