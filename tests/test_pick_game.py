"""Aggregate and Custom pick rows show the same game and start as the other methods."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mix_picks_show_game_and_start():
    node = shutil.which("node")
    assert node, "node is required"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_pick_game.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
