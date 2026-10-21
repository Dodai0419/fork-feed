import datetime as dt, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fork_feed as ff  # noqa: E402
from tests import fakegh  # noqa: E402

GOLDEN = json.loads((ROOT / "tests" / "golden.json").read_text(encoding="utf-8"))
FEED_PATH = "/acme/web-kit/commits/main.atom"


class FakeGitHub(unittest.TestCase):
    def setUp(self):
        self.srv, base = fakegh.serve()
        self.old = ff.API, ff.WEB, os.environ.get("GH_TOKEN")
        ff.API = ff.WEB = base
        os.environ["GH_TOKEN"] = "test-token"
        self.state = str(Path(tempfile.mkdtemp()) / "state.json")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        ff.API, ff.WEB = self.old[:2]
        if self.old[2] is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = self.old[2]

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ff.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def test_same_verdicts_as_forkiq(self):
        # golden = forkiq version_verdict() on these rows (bench/golden.py)
        for row, kind in GOLDEN["verdicts"]:
            self.assertEqual(ff.verdict(row)[0], kind, row)
        rows = {r["fork"]: r for r in (ff.check(f, "test-token") for f in fakegh.FORKS)}
        self.assertEqual({k: r["kind"] for k, r in rows.items()}, {
            "demo/same-lib": "same", "demo/web-kit": "behind", "demo/cli-tool": "contains",
            "demo/rewritten": "diverged", "demo/orphan": "gone", "demo/flaky": "unsynced"})
        self.assertEqual(rows["demo/web-kit"]["text"], "behind 3")
        self.assertEqual(rows["demo/cli-tool"]["text"], "contains upstream (+2 own)")

    def test_same_new_items_as_imozuru_watch(self):
        # golden = what imozuru watch.py check listed as new on 3 looks at the same feed
        state, seen_runs = {}, []
        for step in range(3):
            if step == 2:
                self.srv.RequestHandlerClass.extra[FEED_PATH] = [(0, "Brand new fix")] + fakegh.FEEDS[FEED_PATH]
            got = ff.items(ff.request(ff.WEB + FEED_PATH))
            new, _ = ff.new_items(got, state, ff.WEB + FEED_PATH, dt.datetime.now(dt.timezone.utc), 14, False)
            seen_runs.append([i["link"] for i in new])
        self.assertEqual(seen_runs, GOLDEN["watch_runs"])

    def test_report_first_then_second_look(self):
        code, out = self.run_cli("demo", "--state", self.state)
        self.assertEqual(code, 0)
        self.assertIn("| demo/web-kit | acme/web-kit | behind 3 | v2.0 / v2.3 |", out)
        self.assertIn("## acme/web-kit: behind 3, last 14 days", out)
        self.assertIn("[Add HTTP/3 support]", out)
        self.assertNotIn("Old refactor", out)  # outside the first-look window
        self.assertIn("6 forks: 1 behind, 1 diverged, 1 unsynced, 1 gone, 1 contains, 1 same.", out)
        code, out = self.run_cli("demo", "--state", self.state)
        self.assertIn("## Behind, but nothing new since last look", out)
        self.assertIn("acme/web-kit: behind 3; nothing new, latest", out)

    def test_refuses_dangerous_feed(self):
        with self.assertRaises(ValueError):
            ff.items(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel></channel></rss>')

    def test_errors(self):
        os.environ["GH_TOKEN"] = "wrong"
        self.assertEqual(self.run_cli("demo", "--state", self.state)[0], 2)
        os.environ["GH_TOKEN"] = "test-token"
        code, out = self.run_cli("ghost-user", "--state", self.state)
        self.assertEqual(code, 2)
        self.assertIn("no such user or organization", out)
        code, out = self.run_cli("nofork", "--state", self.state)
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "0 forks: ."))


if __name__ == "__main__":
    unittest.main()
