"""A fake GitHub (GraphQL, compare, commit Atom feeds) for offline tests and the demo.

User "demo" owns six forks, one per verdict: same, behind, contains, diverged (no common
ancestor), gone (parent deleted) and a compare that fails with HTTP 500.
"""
import datetime as dt, json, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


def repo(name, sha, branch="main", tag=None):
    return {"nameWithOwner": name, "defaultBranchRef": {"name": branch, "target": {"oid": sha}},
            "refs": {"nodes": [{"name": tag}] if tag else []}}


FORKS = [
    dict(repo("demo/same-lib", "aaa", tag="v1.0"), isFork=True, parent=repo("up/same-lib", "aaa", tag="v1.0")),
    dict(repo("demo/web-kit", "b01", tag="v2.0"), isFork=True, parent=repo("acme/web-kit", "b99", tag="v2.3")),
    dict(repo("demo/cli-tool", "c02"), isFork=True, parent=repo("tools/cli-tool", "c01", branch="master")),
    dict(repo("demo/rewritten", "d01"), isFork=True, parent=repo("other/rewritten", "d99")),
    dict(repo("demo/orphan", "e01"), isFork=True, parent=None),
    dict(repo("demo/flaky", "f01"), isFork=True, parent=repo("flaky/flaky", "f99")),
]
COMPARE = {"demo/web-kit": (200, {"status": "behind", "ahead_by": 3, "behind_by": 0}),
           "demo/cli-tool": (200, {"status": "ahead", "ahead_by": 0, "behind_by": 2}),
           "demo/rewritten": (404, {"message": "No common ancestor between main and other:main."}),
           "demo/flaky": (500, {"message": "server error"})}


def atom(repo_name, entries, now):
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>Recent Commits to %s</title>" % repo_name]
    for n, (days_ago, title) in enumerate(entries):
        when = (now - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append('<entry><id>c%d</id><link type="text/html" rel="alternate" href="https://github.com/%s/commit/%s"/>'
                   "<title>%s</title><updated>%s</updated><content type=\"html\">&lt;pre&gt;%s&lt;/pre&gt;</content></entry>"
                   % (n, repo_name, title.lower().replace(" ", "-"), title, when, title))
    return "\n".join(out + ["</feed>"]).encode()


FEEDS = {"/acme/web-kit/commits/main.atom": [(1, "Fix cookie parsing"), (3, "Add HTTP/3 support"), (40, "Old refactor")],
         "/flaky/flaky/commits/main.atom": [(2, "never shown")]}


class Handler(BaseHTTPRequestHandler):
    delay = 0.0
    extra = {}  # path -> entries, added by tests

    def _send(self, status, body, ctype="application/json"):
        time.sleep(self.delay)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer test-token":
            return self._send(401, b'{"message": "Bad credentials"}')
        login = req["variables"]["login"]
        nodes = FORKS if login == "demo" else []
        owner = {"repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}
        self._send(200, json.dumps({"data": {"repositoryOwner": owner if login in ("demo", "nofork") else None}}).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/repos/"):
            fork = "/".join(path.split("/")[2:4])
            status, body = COMPARE.get(fork, (404, {"message": "Not Found"}))
            return self._send(status, json.dumps(body).encode())
        entries = self.extra.get(path) or FEEDS.get(path)
        if entries is None:
            return self._send(404, b"not found", "text/plain")
        self._send(200, atom(path.split("/commits")[0].strip("/"), entries, dt.datetime.now(dt.timezone.utc)),
                   "application/atom+xml; charset=utf-8")

    def log_message(self, *args):
        pass


def serve(delay=0.0):
    server = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (Handler,), {"delay": delay, "extra": {}}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]
