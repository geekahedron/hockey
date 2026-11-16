"""The player tile shows position and opens the inputs dialog."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_page_formats_player_inputs():
    node = shutil.which("node")
    assert node, "node is required to check the player dialog"
    proc = subprocess.run(
        [node, os.path.join(ROOT, "tests", "test_player_detail.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr


def test_dialog_markup_closes_three_ways():
    html = open(os.path.join(ROOT, "web", "index.html")).read()
    script = open(os.path.join(ROOT, "web", "app.js")).read()
    assert 'id="player-detail"' in html
    assert 'id="player-detail-close"' in html
    assert 'aria-label="Close"' in html
    assert "event.target === dialog" in script
    assert 'event.key !== "Escape"' in script
    assert "player-detail-close" in script
    assert 'class: "pill pos"' in script
