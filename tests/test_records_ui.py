"""The records sentence and grouped list changes."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_records_line_and_grouped_changes():
    node = shutil.which("node")
    assert node, "node is required"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_records_ui.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
