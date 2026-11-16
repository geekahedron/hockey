"""The page renders injury and returning badges from the day JSON."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_page_formats_injury_badges():
    node = shutil.which("node")
    assert node, "node is required to check the badges"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_injury_badge.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
