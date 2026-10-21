"""Offline demo: run fork-feed twice against a fake GitHub with six forks (one per verdict)."""
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fork_feed  # noqa: E402
from tests import fakegh  # noqa: E402

srv, base = fakegh.serve()
fork_feed.API = fork_feed.WEB = base
os.environ["GH_TOKEN"] = "test-token"  # the fake server's token, not a real one
state = str(Path(tempfile.mkdtemp()) / "state.json")
print("$ python fork_feed.py demo            # first look\n")
code = fork_feed.main(["demo", "--state", state])
print("\n$ python fork_feed.py demo            # second look: nothing new\n")
code = code or fork_feed.main(["demo", "--state", state])
srv.shutdown()
sys.exit(code)
