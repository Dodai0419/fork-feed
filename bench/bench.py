"""Time imozuru watch.py (one feed after another) against fork-feed on a real user's forks.

    GH_TOKEN=$(gh auth token) python bench/bench.py <imozuru checkout> <github user> [runs=3]

imozuru watches the commit feeds of every upstream (added once with `watch.py add`), then
`check --fresh` is timed. fork-feed is timed doing everything: list forks, compare each, read
the same feeds. Network-bound: expect the numbers to move with GitHub's response times.
"""
import os, statistics, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fork_feed  # noqa: E402

watch = Path(sys.argv[1]) / "skills" / "imozuru" / "scripts" / "watch.py"
user, runs = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3
token = os.environ["GH_TOKEN"]
rows = [fork_feed.check(f, token) for f in fork_feed.list_forks(user, token)]
feeds = ["%s/%s/commits/%s.atom" % (fork_feed.WEB, r["upstream"], r["branch"]) for r in rows if r["kind"] == "behind"]
topic = Path(tempfile.mkdtemp())
for f in feeds:
    subprocess.run([sys.executable, str(watch), "add", str(topic), f], capture_output=True)
env = dict(os.environ, PYTHONIOENCODING="utf-8")
cmds = {"imozuru watch.py check (%d feeds)" % len(feeds): [sys.executable, str(watch), "check", str(topic), "--fresh"],
        "fork-feed --jobs 1": [sys.executable, str(ROOT / "fork_feed.py"), user, "--fresh", "--jobs", "1", "--state", str(topic / "ff1.json")],
        "fork-feed --jobs 8": [sys.executable, str(ROOT / "fork_feed.py"), user, "--fresh", "--state", str(topic / "ff8.json")]}
print("%d forks, %d behind" % (len(rows), len(feeds)))
for name, cmd in cmds.items():
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", env=env)
        times.append((time.perf_counter() - t) * 1000)
    print("%-34s median %6.0f ms of %d (exit %d)" % (name, statistics.median(times), runs, p.returncode))
