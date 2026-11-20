"""The Today page shows the slate date and asks the server when it is stale."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_today_page_names_the_slate_date():
    node = shutil.which("node")
    assert node, "node is required"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_slate_date.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
