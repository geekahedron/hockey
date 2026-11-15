"""The hourly wrapper, with a fake clock and a fake Python. No live Tims."""
import os
import stat
import subprocess


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "job", "cron_run.sh")


def _home(tmp_path, hour, today_doc=None, exit_code=75):
    home = tmp_path / "home"
    bindir = home / "tims-venv" / "bin"
    bindir.mkdir(parents=True)
    publish = home / "tims-hockey" / "publish"
    publish.mkdir(parents=True)
    (publish / "marker.txt").write_text("published")
    (home / "public_html" / "tools" / "hockey" / "data").mkdir(parents=True)
    if today_doc is not None:
        (publish / "today.json").write_text(today_doc)
    py = bindir / "python"
    py.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  exec /usr/bin/python3 -c \"$2\" \"$3\"\n"
        "fi\n"
        "mkdir -p \"$HOME/tims-hockey/logs\"\n"
        "echo \"$@\" >> \"$HOME/tims-hockey/logs/python.args\"\n"
        "exit %d\n" % exit_code
    )
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    date_bin = fakes / "date"
    date_bin.write_text(
        "#!/bin/sh\n"
        "hour=\"${CRON_TEST_HOUR:-03}\"\n"
        "day=\"${CRON_TEST_DATE:-2026-11-15}\"\n"
        "case \"$1\" in\n"
        "  +%H) printf '%s\\n' \"$hour\" ;;\n"
        "  +%Y-%m-%d) printf '%s\\n' \"$day\" ;;\n"
        "  '+%Y-%m-%d %H:%M:%S') printf '%s 03:05:00\\n' \"$day\" ;;\n"
        "  *) printf '%s\\n' \"$day\" ;;\n"
        "esac\n"
    )
    date_bin.chmod(date_bin.stat().st_mode | stat.S_IEXEC)
    rsync_bin = fakes / "rsync"
    rsync_bin.write_text(
        "#!/bin/sh\n"
        "src= dest=\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    -*) ;;\n"
        "    *) if [ -z \"$src\" ]; then src=$arg; else dest=$arg; fi ;;\n"
        "  esac\n"
        "done\n"
        "mkdir -p \"$dest\"\n"
        "cp -a \"${src}/.\" \"$dest/\"\n"
    )
    rsync_bin.chmod(rsync_bin.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "%s:/usr/bin:/bin" % fakes
    env["CRON_TEST_HOUR"] = hour
    env["CRON_TEST_DATE"] = "2026-11-15"
    return home, env


def _run(env):
    return subprocess.run(
        ["/bin/sh", SCRIPT],
        env=env,
        capture_output=True,
        text=True,
    )


def test_wrapper_skips_outside_the_toronto_window(tmp_path):
    home, env = _home(tmp_path, "02")
    proc = _run(env)
    assert proc.returncode == 0
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "skip hour 2" in log
    assert not (home / "tims-hockey" / "logs" / "python.args").exists()


def test_wrapper_retries_a_not_ready_slate_and_rsyncs(tmp_path):
    home, env = _home(tmp_path, "03", exit_code=75)
    proc = _run(env)
    assert proc.returncode == 75
    assert (home / "public_html" / "tools" / "hockey" / "data" / "marker.txt").read_text() == "published"
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text().strip().splitlines()
    assert len(log) == 1
    assert "exit 75 rsync" in log[0]


def test_wrapper_skips_when_today_is_already_graded(tmp_path):
    home, env = _home(
        tmp_path,
        "09",
        today_doc='{"date": "2026-11-15", "status": "graded"}\n',
        exit_code=0,
    )
    proc = _run(env)
    assert proc.returncode == 0
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "skip today graded" in log
    assert not (home / "tims-hockey" / "logs" / "python.args").exists()


def test_wrapper_runs_when_today_is_still_pending(tmp_path):
    home, env = _home(
        tmp_path,
        "13",
        today_doc='{"date": "2026-11-15", "status": "pending"}\n',
        exit_code=0,
    )
    proc = _run(env)
    assert proc.returncode == 0
    assert (home / "tims-hockey" / "logs" / "python.args").exists()
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "exit 0 rsync" in log


def test_wrapper_does_not_rsync_a_hard_error(tmp_path):
    home, env = _home(tmp_path, "04", exit_code=1)
    proc = _run(env)
    assert proc.returncode == 1
    assert not (home / "public_html" / "tools" / "hockey" / "data" / "marker.txt").exists()
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "exit 1" in log
    assert "rsync" not in log
