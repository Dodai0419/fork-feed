"""Regenerate tests/golden.json from the upstream code, against the fake GitHub in tests/fakegh.py.

    python bench/golden.py <forkiq checkout> <imozuru checkout>

forkiq: app/versions.py version_verdict() on the rows fork-feed builds (forkiq's engine needs a
GitHub App, a server and fcntl, so only its verdict function is run). imozuru: watch.py add + check,
three times (first look, nothing new, one new commit), recording the links it lists as new.
"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), sys.argv[1]]
import fork_feed  # noqa: E402
from tests import fakegh  # noqa: E402
from app.versions import version_verdict  # noqa: E402

srv, base = fakegh.serve()
fork_feed.API = fork_feed.WEB = base
rows = [fork_feed.check(f, "test-token") for f in fakegh.FORKS]
extra = [{"fork_sha": "a", "upstream_sha": "b", "status": "pending"},                       # counts unknown
         {"fork_sha": "a", "upstream_sha": "b", "status": "error", "last_error": "boom"},
         {"fork_sha": "a", "upstream_sha": "b", "status": "pending", "upstream_ahead": 2, "fork_ahead": 5},
         {"fork_sha": "a", "upstream_sha": "b", "status": "pending", "upstream_ahead": 0, "fork_ahead": 0},
         {"fork_sha": "", "upstream_sha": "b", "status": "pending"}]
verdicts = []
for r in [{k: v for k, v in r.items() if k not in ("kind", "text")} for r in rows] + extra:
    full = dict({"fork_sha": None, "upstream_sha": None, "last_merged_upstream_sha": None, "status": "pending",
                 "upstream_gone": False, "upstream_ahead": None, "fork_ahead": None, "last_error": None}, **r)
    verdicts.append([r, version_verdict(full)["kind"]])

watch = Path(sys.argv[2]) / "skills" / "imozuru" / "scripts" / "watch.py"
topic = Path(tempfile.mkdtemp())
feed = base + "/acme/web-kit/commits/main.atom"
subprocess.run([sys.executable, str(watch), "add", str(topic), feed, "web-kit"], capture_output=True)
runs = []
NOTHING_NEW = "".join(map(chr, (0x65b0, 0x7740, 0x306a, 0x3057)))  # imozuru prints this when nothing is new
for step in range(3):
    if step == 2:  # one new commit upstream
        srv.RequestHandlerClass.extra["/acme/web-kit/commits/main.atom"] = [(0, "Brand new fix")] + fakegh.FEEDS["/acme/web-kit/commits/main.atom"]
    out = subprocess.run([sys.executable, str(watch), "check", str(topic)], capture_output=True, encoding="utf-8",
                         env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
    new_part = out.split("##")[1] if "##" in out else ""
    runs.append([] if NOTHING_NEW in out.split("##")[0] else re.findall(r"\]\((https://[^)]+)\)", new_part))
srv.shutdown()
(ROOT / "tests" / "golden.json").write_text(json.dumps({"verdicts": verdicts, "watch_runs": runs}, indent=1), encoding="utf-8")
print([v[1] for v in verdicts], runs)
