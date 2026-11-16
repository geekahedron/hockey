"""Custom mix and the record counters stay in the page script."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mix_rules_and_streaks():
    node = shutil.which("node")
    assert node, "node is required"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_mix.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
