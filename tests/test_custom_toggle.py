"""The Custom mix menu, the show toggle, and the collapsible settings header."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_custom_mix_toggle_and_panel():
    node = shutil.which("node")
    assert node, "node is required"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_custom_toggle.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
