"""The page shows each player's NHL start in Toronto time."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_page_formats_toronto_game_time():
    node = shutil.which("node")
    assert node, "node is required to check the page clock"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_game_time.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
