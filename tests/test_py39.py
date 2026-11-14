"""The model, the daily job, and the tests stay on Python 3.9 syntax."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _vermin():
    sibling = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "vermin")
    if os.path.isfile(sibling) and os.access(sibling, os.X_OK):
        return sibling
    found = shutil.which("vermin")
    assert found, "vermin is not installed (pip install vermin)"
    return found


def test_vermin_accepts_python_39():
    proc = subprocess.run(
        [_vermin(), "-t=3.9-", "--no-tips", "model", "job", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
