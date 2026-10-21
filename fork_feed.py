#!/usr/bin/env python3
"""fork-feed: see which of your GitHub forks are behind upstream, and what landed upstream since you last looked.

    GH_TOKEN=$(gh auth token) python fork_feed.py USER            # all forks of USER
    python fork_feed.py USER --days 30 --fresh --state FILE       # first-run window, ignore what was seen

One GraphQL call lists every fork with both heads; one compare per changed fork (in parallel)
gives the verdict; each lagging upstream's commit Atom feed shows only what you have not seen.
Verdicts follow zzusec/forkiq app/versions.py; feed parsing and "seen" state follow
MaryCache/imozuru watch.py. Read-only: never syncs, merges or writes to GitHub.
"""
import argparse, datetime as dt, email.utils, html, json, os, re, sys, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = os.environ.get("FORK_FEED_API", "https://api.github.com")
WEB = os.environ.get("FORK_FEED_WEB", "https://github.com")
ATOM = "{http://www.w3.org/2005/Atom}"
HEAD_CHARS, SEEN_LIMIT = 120, 500
QUERY = """query($login: String!, $after: String) { repositoryOwner(login: $login) {
  repositories(isFork: true, first: 100, after: $after, ownerAffiliations: OWNER) {
    pageInfo { hasNextPage endCursor }
    nodes { nameWithOwner isFork defaultBranchRef { name target { oid } }
      refs(refPrefix: "refs/tags/", first: 1, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) { nodes { name } }
      parent { nameWithOwner defaultBranchRef { name target { oid } }
        refs(refPrefix: "refs/tags/", first: 1, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) { nodes { name } } } } } } }"""


def request(url, body=None, token=None):
    headers = {"User-Agent": "fork-feed", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None, headers)
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read(5_000_000)


# --- forks and verdicts (forkiq) ------------------------------------------------------------
def list_forks(user, token):
    forks, after = [], None
    while True:
        data = json.loads(request(API + "/graphql", {"query": QUERY, "variables": {"login": user, "after": after}}, token))
        if data.get("errors"):
            raise RuntimeError("GitHub GraphQL: " + "; ".join(e.get("message", "") for e in data["errors"]))
        repos = ((data.get("data") or {}).get("repositoryOwner") or {}).get("repositories")
        if repos is None:
            raise RuntimeError("no such user or organization: " + user)
        forks += repos["nodes"]
        if not repos["pageInfo"]["hasNextPage"]:
            return forks
        after = repos["pageInfo"]["endCursor"]


def compare(fork, token):
    """forkiq's probe: compare(base=fork branch, head=upstream owner:branch). None = no common ancestor."""
    p = fork["parent"]
    # page 2 of 1-commit pages: same ahead_by/behind_by, but GitHub leaves out the file list
    # (950 KB -> 17 KB for a fork 6935 commits behind)
    url = "%s/repos/%s/compare/%s...%s:%s?per_page=1&page=2" % (API, fork["nameWithOwner"], fork["defaultBranchRef"]["name"],
                                            p["nameWithOwner"].split("/")[0], p["defaultBranchRef"]["name"])
    try:
        return json.loads(request(url, token=token))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def verdict(row):
    """forkiq version_verdict() on a read-only row: same / behind N / contains (ahead N) / diverged / gone / unsynced."""
    fork, up = row.get("fork_sha") or "", row.get("upstream_sha") or ""
    behind, ahead = row.get("upstream_ahead"), row.get("fork_ahead")
    if row.get("upstream_gone"):
        return "gone", "upstream gone"
    if not fork or not up:
        return "pending", "no default branch"
    if fork == up:
        return "same", "same version"
    if row.get("status") in ("diverged", "blocked"):
        return "diverged", "diverged: " + (row.get("last_error") or "both sides have their own commits").strip()
    if behind:
        return "behind", "behind %d" % behind + (" (and %d own)" % ahead if ahead else "")
    if row.get("status") in ("error", "needs_attention", "missing", "paused"):
        return "unsynced", "not checked: " + ((row.get("last_error") or "").strip() or "check failed")
    if ahead is not None:
        return "contains", "contains upstream" + (" (+%d own)" % ahead if ahead else "")
    if row.get("status") in ("behind", "pending"):
        return "behind", "behind"
    return "unsynced", "unknown"


def _tag(repo):
    nodes = (repo.get("refs") or {}).get("nodes") or []
    return nodes[0]["name"] if nodes else None


def check(fork, token):
    p = fork.get("parent") or {}
    row = {"fork": fork["nameWithOwner"], "upstream": p.get("nameWithOwner"), "status": "pending",
           "upstream_gone": not fork.get("isFork", True) or not p.get("nameWithOwner"),
           "fork_sha": ((fork.get("defaultBranchRef") or {}).get("target") or {}).get("oid"),
           "upstream_sha": ((p.get("defaultBranchRef") or {}).get("target") or {}).get("oid"),
           "branch": (p.get("defaultBranchRef") or {}).get("name"), "fork_tag": _tag(fork), "upstream_tag": _tag(p)}
    if not row["upstream_gone"] and row["fork_sha"] and row["upstream_sha"] and row["fork_sha"] != row["upstream_sha"]:
        try:
            c = compare(fork, token)
            if c is None:
                row.update(status="diverged", last_error="no common ancestor (history rewritten)")
            else:
                row.update(upstream_ahead=int(c.get("ahead_by") or 0), fork_ahead=int(c.get("behind_by") or 0))
        except Exception as e:  # one broken fork must not hide the others
            row.update(status="error", last_error="%s: %s" % (type(e).__name__, e))
    row["kind"], row["text"] = verdict(row)
    return row


# --- upstream feeds (imozuru watch) ---------------------------------------------------------
def plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def items(feed_bytes):
    """RSS 2.0 and Atom entries as title/link/date/head. Feeds with DOCTYPE/ENTITY are refused (XML bombs)."""
    root_at = re.search(rb"<(rss|feed|rdf:RDF)\b", feed_bytes)
    if re.search(rb"<!(DOCTYPE|ENTITY)", feed_bytes[:root_at.start()] if root_at else feed_bytes, re.I):
        raise ValueError("refusing a feed with DOCTYPE or ENTITY")
    root, out = ET.fromstring(feed_bytes), []
    for it in root.iter("item"):
        out.append({"title": plain(it.findtext("title")), "link": (it.findtext("link") or "").strip(),
                    "date": parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
                    "head": plain(it.findtext("description"))})
    for en in root.iter(ATOM + "entry"):
        link = next((ln.get("href", "") for ln in en.findall(ATOM + "link") if ln.get("rel", "alternate") == "alternate"), "")
        out.append({"title": plain(en.findtext(ATOM + "title")), "link": link,
                    "date": parse_date(en.findtext(ATOM + "published") or en.findtext(ATOM + "updated")),
                    "head": plain(en.findtext(ATOM + "summary") or en.findtext(ATOM + "content"))})
    return out


def new_items(got, state, feed, now, days, fresh):
    """imozuru's rule: unseen links; on the first look only the last `days`. Updates state."""
    seen = set() if fresh else set(state.get(feed, []))
    first = fresh or feed not in state
    cutoff = now - dt.timedelta(days=days)
    new = [i for i in got if i["link"] and i["link"] not in seen and (not first or (i["date"] and i["date"] >= cutoff))]
    new.sort(key=lambda i: i["date"] or now, reverse=True)
    links = [i["link"] for i in got]
    state[feed] = (links + list(set(state.get(feed, [])) - set(links)))[:SEEN_LIMIT]
    return new, first


# --- report ---------------------------------------------------------------------------------
def report(user, rows, feeds, state, now, days, fresh):
    order = {"behind": 0, "diverged": 1, "unsynced": 2, "gone": 3, "pending": 4, "contains": 5, "same": 6}
    rows.sort(key=lambda r: (order[r["kind"]], r["fork"].lower()))
    lines = ["# Forks of %s (%s)" % (user, now.astimezone().strftime("%Y-%m-%d %H:%M")), "",
             "| fork | upstream | verdict | latest tag (fork / upstream) |", "|---|---|---|---|"]
    lines += ["| %s | %s | %s | %s / %s |" % (r["fork"], r["upstream"] or "-", r["text"], r["fork_tag"] or "-",
                                             r["upstream_tag"] or "-") for r in rows]
    quiet = []
    for r in rows:
        if r["kind"] != "behind":
            continue
        feed = "%s/%s/commits/%s.atom" % (WEB, r["upstream"], r["branch"])
        got = feeds.get(feed)
        if isinstance(got, Exception):
            lines += ["", "## %s: %s" % (r["upstream"], r["text"]), "- feed failed: %s: %s" % (type(got).__name__, got)]
            continue
        new, first = new_items(got, state, feed, now, days, fresh)
        if not new:
            dated = [i for i in got if i["date"]]
            last = max(dated, key=lambda i: i["date"]) if dated else None
            quiet.append("- %s: %s; nothing new%s" % (r["upstream"], r["text"], ", latest %s [%s](%s)" % (
                last["date"].astimezone().strftime("%Y-%m-%d"), last["title"], last["link"]) if last else ""))
            continue
        lines += ["", "## %s: %s%s" % (r["upstream"], r["text"], ", last %d days" % days if first else ", new since last look")]
        for i in new:
            day = i["date"].astimezone().strftime("%Y-%m-%d") if i["date"] else "no date"
            lines.append("- %s [%s](%s)" % (day, i["title"], i["link"]))
    if quiet:
        lines += ["", "## Behind, but nothing new since last look"] + quiet
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in order}
    lines += ["", "%d forks: %s." % (len(rows), ", ".join("%d %s" % (n, k) for k, n in counts.items() if n))]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("user", help="GitHub user or organization whose forks to check")
    ap.add_argument("--state", default=".fork-feed.json", help="what was already seen (default .fork-feed.json)")
    ap.add_argument("--days", type=int, default=14, help="first look at a feed: show the last N days (default 14)")
    ap.add_argument("--fresh", action="store_true", help="ignore what was seen; use only the --days window")
    ap.add_argument("--jobs", type=int, default=8, help="parallel requests (default 8)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # commit titles in any language must not crash the report
        sys.stdout.reconfigure(errors="replace")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: set GH_TOKEN or GITHUB_TOKEN (GitHub GraphQL needs a token; read-only is enough)", file=sys.stderr)
        return 2
    try:
        forks = list_forks(a.user, token)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        rows = list(pool.map(lambda f: check(f, token), forks))
        urls = ["%s/%s/commits/%s.atom" % (WEB, r["upstream"], r["branch"]) for r in rows if r["kind"] == "behind"]

        def feed(u):
            try:
                return items(request(u))
            except Exception as e:  # one dead feed must not hide the others
                return e
        feeds = dict(zip(urls, pool.map(feed, urls)))
    state_p = Path(a.state)
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    print(report(a.user, rows, feeds, state, dt.datetime.now(dt.timezone.utc), a.days, a.fresh))
    state_p.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
